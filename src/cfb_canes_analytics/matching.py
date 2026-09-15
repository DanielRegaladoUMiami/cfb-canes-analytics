"""Match Kalshi events to ESPN games.

Kalshi codes are its own (``ULL`` where ESPN says ``UL``, ``CHAR`` where ESPN says
``CLT``), so abbreviations alone match only about half the schedule. The event *title*
carries readable school names ("Louisiana vs USC"), and ESPN exposes a ``location``
field with the same shape ("Louisiana", "USC"), so normalised names are the reliable
key. Both sources order the teams away-first.

Matching is deliberately conservative: a game is matched only when BOTH sides agree.
Anything else is reported as unmatched rather than guessed, because a wrong join
silently corrupts every downstream calibration number. The date is allowed to differ by
one day, because a late kickoff in Hawai'i and a game played in Ireland land on
different calendar days for the two sources; both names must still agree.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

#: Applied after normalisation, to the whole string.
_REPLACEMENTS = [
    (r"\bst\b", "state"),
    (r"\buniv\b", "university"),
    (r"\bu\b", "university"),
    (r"&", "and"),
]

_NOISE = re.compile(r"\b(university|the|of)\b")
#: "University at Albany" normalises to "at albany" once "university" is dropped.
_LEADING_AT = re.compile(r"^at ")

#: Schools the two sources spell differently enough that normalisation cannot bridge
#: them. Keys and values are already-normalised strings; both sides are mapped, so the
#: direction does not matter. Extend this when ``cfb check`` reports an unmatched game.
ALIASES = {
    "ualbany": "albany",
    "liu": "long island",
    "nc state": "north carolina state",
    "ut martin": "tennessee martin",
    "uconn": "connecticut",
    "umass": "massachusetts",
    "utsa": "texas san antonio",
    "utep": "texas el paso",
    "ucf": "central florida",
    "fiu": "florida international",
    "fau": "florida atlantic",
    "smu": "southern methodist",
    "tcu": "texas christian",
    "lsu": "louisiana state",
    "byu": "brigham young",
    "ole miss": "mississippi",
    "pitt": "pittsburgh",
}


def normalize(name: str) -> str:
    """Casefold, strip accents and punctuation, expand abbreviations."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Apostrophes join letters ("Hawai'i" -> "hawaii"); other punctuation separates them.
    text = re.sub(r"[\u2018\u2019\u02bb']", "", text)
    text = text.lower().replace("&", " & ")
    text = re.sub(r"[^a-z0-9& ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for pattern, repl in _REPLACEMENTS:
        text = re.sub(pattern, repl, text)
    text = _NOISE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = _LEADING_AT.sub("", text)
    return ALIASES.get(text, text)


def names_agree(left: str, right: str) -> bool:
    """True when two school names refer to the same school.

    Containment handles "Miami (FL)" vs "Miami" and "Hawai'i" vs "Hawaii"; it is applied
    only on whole normalised strings so "Miami" does not swallow "Miami (OH)" — those
    normalise to "miami fl" and "miami oh", neither containing the other.
    """
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return False
    return a == b or a.startswith(b + " ") or b.startswith(a + " ")


@dataclass(frozen=True, slots=True)
class MatchResult:
    matched: dict[str, str]  # kalshi event_ticker -> espn game_id
    unmatched: list[str]  # kalshi event tickers with no confident ESPN game
    ambiguous: list[str]  # more than one ESPN game fit


def _espn_index(games: Iterable[dict[str, Any]]) -> dict[date, list[dict[str, Any]]]:
    index: dict[date, list[dict[str, Any]]] = {}
    for game in games:
        index.setdefault(game["game_date_et"], []).append(game)
    return index


def _fits(event: dict[str, Any], game: dict[str, Any]) -> bool:
    """Both teams must agree, in either order.

    Order is ignored because Kalshi does not list the away team first consistently
    ("Alabama A&M vs Howard" is Howard *at* Alabama A&M), and a total is symmetric
    anyway. Two teams cannot meet twice on the same date, so this cannot create a false
    positive that ordered matching would have avoided.
    """
    if event.get("away") and event.get("home"):
        pair = {event["away"], event["home"]}
        if pair == {game["away_abbr"], game["home_abbr"]} and "" not in pair:
            return True
    away_name, home_name = event.get("away_name"), event.get("home_name")
    if not away_name or not home_name:
        return False
    straight = names_agree(away_name, game["away_location"]) and names_agree(
        home_name, game["home_location"]
    )
    swapped = names_agree(away_name, game["home_location"]) and names_agree(
        home_name, game["away_location"]
    )
    return straight or swapped


def match_events(events: Iterable[dict[str, Any]], games: Iterable[dict[str, Any]]) -> MatchResult:
    """Join Kalshi events to ESPN games on date plus both team identities."""
    index = _espn_index(games)
    matched: dict[str, str] = {}
    unmatched: list[str] = []
    ambiguous: list[str] = []
    for event in events:
        game_date = event["game_date"]
        nearby = [
            g for offset in (0, -1, 1) for g in index.get(game_date + timedelta(days=offset), [])
        ]
        fits = [g for g in nearby if _fits(event, g)]
        if len(fits) == 1:
            matched[event["event_ticker"]] = fits[0]["game_id"]
        elif not fits:
            unmatched.append(event["event_ticker"])
        else:
            ambiguous.append(event["event_ticker"])
    return MatchResult(matched=matched, unmatched=unmatched, ambiguous=ambiguous)
