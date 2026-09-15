"""ESPN's public college-football scoreboard: schedule, venue flags, final scores.

No key required. ``groups=80`` restricts to FBS. Names read "Away at Home". This is also
Kalshi's settlement source, so scores here are what totals markets settle on. ESPN week
numbering is canonical for this repo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ._http import RetryingClient

SITE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
FBS_GROUP = 80
REGULAR_SEASON = 2
POSTSEASON = 3
EASTERN = ZoneInfo("America/New_York")


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class TeamSide:
    id: str
    abbreviation: str
    display_name: str
    location: str
    score: int | None
    winner: bool | None


@dataclass(frozen=True, slots=True)
class Game:
    id: str
    name: str
    kickoff: datetime
    season: int
    week: int
    status: str
    completed: bool
    neutral_site: bool
    venue: str | None
    indoor: bool | None
    home: TeamSide
    away: TeamSide
    odds_provider: str | None
    over_under: float | None
    spread: float | None

    @property
    def total(self) -> int | None:
        if not self.completed or self.home.score is None or self.away.score is None:
            return None
        return self.home.score + self.away.score

    @property
    def game_date_et(self) -> date:
        """US-Eastern calendar date — what Kalshi tickers and Polymarket slugs use."""
        return self.kickoff.astimezone(EASTERN).date()

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Game:
        comp = (raw.get("competitions") or [{}])[0]
        sides: dict[str, TeamSide] = {}
        for c in comp.get("competitors") or []:
            team = c.get("team") or {}
            sides[c.get("homeAway", "")] = TeamSide(
                id=str(team.get("id", "")),
                abbreviation=team.get("abbreviation") or "",
                display_name=team.get("displayName") or "",
                location=team.get("location") or "",
                score=_int(c.get("score")),
                winner=c.get("winner"),
            )
        odds = (comp.get("odds") or [{}])[0]
        venue = comp.get("venue") or {}
        status = (raw.get("status") or {}).get("type") or {}
        return cls(
            id=str(raw["id"]),
            name=raw.get("name") or "",
            kickoff=datetime.fromisoformat(str(raw["date"]).replace("Z", "+00:00")).astimezone(UTC),
            season=int((raw.get("season") or {}).get("year") or 0),
            week=int((raw.get("week") or {}).get("number") or 0),
            status=status.get("name") or "",
            completed=bool(status.get("completed", False)),
            neutral_site=bool(comp.get("neutralSite", False)),
            venue=venue.get("fullName"),
            indoor=venue.get("indoor"),
            home=sides.get("home") or TeamSide("", "", "", "", None, None),
            away=sides.get("away") or TeamSide("", "", "", "", None, None),
            odds_provider=((odds.get("provider") or {}).get("name")),
            over_under=_float(odds.get("overUnder")),
            spread=_float(odds.get("spread")),
        )


def parse_scoreboard(raw: dict[str, Any]) -> tuple[int, list[Game]]:
    """(week number the scoreboard is showing, games)."""
    week = int((raw.get("week") or {}).get("number") or 0)
    games = [Game.from_api(e) for e in raw.get("events") or []]
    return week, games


class EspnClient(RetryingClient):
    def __init__(self, base_url: str = SITE_URL, **kwargs: Any) -> None:
        kwargs.setdefault("min_interval", 0.5)
        super().__init__(base_url, **kwargs)

    def scoreboard(
        self,
        year: int,
        week: int | None = None,
        *,
        season_type: int = REGULAR_SEASON,
        group: int = FBS_GROUP,
    ) -> tuple[int, list[Game]]:
        """Games for one week (``None`` = ESPN's current week)."""
        raw = self.get_json(
            "scoreboard",
            {
                "groups": group,
                "week": week,
                "seasontype": season_type,
                "dates": year,
                "limit": 400,
            },
        )
        return parse_scoreboard(raw)
