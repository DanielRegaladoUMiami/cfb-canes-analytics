"""Polymarket per-game college football markets (Gamma metadata + CLOB prices).

Verified 2026-09-14, all public without a key:

- Gamma ``GET /events?slug=cfb-<away>-<home>-<YYYY-MM-DD>`` (e.g. ``cfb-mia-wake-2026-09-18``)
  returns a list with one event whose ``markets`` include the moneyline, one or more
  ``Spread: ...`` markets and one or more ``"A vs. B: O/U 51.5"`` markets. Team slugs are
  Polymarket's own (``flst`` = Florida State, ``bama``/``ala`` both seen), so slugs are
  resolved through ``/public-search`` rather than guessed.
- O/U markets carry ``line``, ``outcomes`` ``["Over","Under"]`` (JSON strings),
  ``outcomePrices`` (mid-ish marks), ``bestBid``/``bestAsk`` for the Over token,
  ``clobTokenIds`` (Over first), ``gameStartTime``.
- CLOB ``/midpoint``, ``/book`` and ``/prices-history`` take a token id.
- Cost of execution is the bid/ask spread; buying Over pays ``bestAsk``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from ._http import RetryingClient

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"
CFB_SLUG_PREFIX = "cfb-"

#: ``"Florida State vs. Alabama: O/U 50.5"`` and nothing else. Half, quarter, team-total
#: and touchdown markets all carry a ``line`` too, so they must be excluded by shape.
GAME_TOTAL_QUESTION = re.compile(r"^.+ vs\. .+: O/U \d+(?:\.\d+)?$")
GAME_TOTAL = "game_total"


def _json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return json.loads(value)


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _game_start(value: Any) -> datetime | None:
    """``"2026-09-18 23:30:00+00"`` or ISO with ``Z``."""
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    if text.endswith("+00"):
        text += ":00"
    return datetime.fromisoformat(text).astimezone(UTC)


def classify_question(question: str) -> str:
    """``game_total`` for the full-game line; a coarse label for everything else."""
    if GAME_TOTAL_QUESTION.match(question):
        return GAME_TOTAL
    lowered = question.lower()
    if "total touchdowns" in lowered:
        return "touchdowns"
    if "team total" in lowered:
        return "team_total"
    if re.search(r"\b[12][HQ]\b", question):
        return "period_total"
    return "other"


@dataclass(frozen=True, slots=True)
class OverUnderMarket:
    market_id: str
    event_slug: str
    question: str
    kind: str
    line: float
    over_token: str
    under_token: str
    over_mark: float | None
    best_bid: float | None
    best_ask: float | None
    liquidity: float | None
    volume: float | None
    game_start: datetime | None
    active: bool
    closed: bool

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    @classmethod
    def from_gamma(cls, raw: dict[str, Any], event_slug: str) -> OverUnderMarket:
        question = raw.get("question") or ""
        tokens = _json_list(raw.get("clobTokenIds"))
        prices = [_float(p) for p in _json_list(raw.get("outcomePrices"))]
        return cls(
            market_id=str(raw.get("id")),
            event_slug=event_slug,
            question=question,
            kind=classify_question(question),
            line=float(raw["line"]),
            over_token=str(tokens[0]) if tokens else "",
            under_token=str(tokens[1]) if len(tokens) > 1 else "",
            over_mark=prices[0] if prices else None,
            best_bid=_float(raw.get("bestBid")),
            best_ask=_float(raw.get("bestAsk")),
            liquidity=_float(raw.get("liquidityNum")),
            volume=_float(raw.get("volumeNum")),
            game_start=_game_start(raw.get("gameStartTime")),
            active=bool(raw.get("active", False)),
            closed=bool(raw.get("closed", False)),
        )


def is_over_under(raw: dict[str, Any]) -> bool:
    outcomes = [str(o).lower() for o in _json_list(raw.get("outcomes"))]
    return raw.get("line") is not None and outcomes[:2] == ["over", "under"]


def parse_over_under_markets(
    event: dict[str, Any], *, kind: str | None = None
) -> list[OverUnderMarket]:
    """Every Over/Under market on an event, optionally filtered to one ``kind``."""
    slug = event.get("slug") or ""
    markets = [
        OverUnderMarket.from_gamma(raw, slug)
        for raw in event.get("markets") or []
        if is_over_under(raw)
    ]
    if kind is not None:
        markets = [m for m in markets if m.kind == kind]
    markets.sort(key=lambda m: (m.kind, m.line))
    return markets


def pick_game_event(
    candidates: list[dict[str, Any]], game_date: date, *, prefix: str = CFB_SLUG_PREFIX
) -> dict[str, Any] | None:
    """Choose the ``cfb-*`` event whose slug ends with the (US-Eastern) game date."""
    suffix = game_date.isoformat()
    for event in candidates:
        slug = event.get("slug") or ""
        if slug.startswith(prefix) and slug.endswith(suffix):
            return event
    return None


class PolymarketClient:
    """Gamma (metadata) + CLOB (prices), both public."""

    def __init__(self, gamma_url: str = GAMMA_URL, clob_url: str = CLOB_URL, **kwargs: Any) -> None:
        self.gamma = RetryingClient(gamma_url, **kwargs)
        self.clob = RetryingClient(clob_url, **kwargs)

    def __enter__(self) -> PolymarketClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.gamma.close()
        self.clob.close()

    # ------------------------------------------------------------------ Gamma

    def get_event(self, slug: str) -> dict[str, Any] | None:
        events = self.gamma.get_json("events", {"slug": slug})
        return events[0] if events else None

    def search_events(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        page = self.gamma.get_json("public-search", {"q": query, "limit_per_type": limit})
        return page.get("events") or []

    def find_game_event(self, away: str, home: str, game_date: date) -> dict[str, Any] | None:
        """Resolve a game to its Polymarket event via search; ``None`` if not listed."""
        for query in (f"{away} {home}", f"{home} {away}"):
            if event := pick_game_event(self.search_events(query), game_date):
                slug = event.get("slug")
                return self.get_event(slug) if slug else event
        return None

    # ------------------------------------------------------------------- CLOB

    def midpoint(self, token_id: str) -> float | None:
        return _float(self.clob.get_json("midpoint", {"token_id": token_id}).get("mid"))

    def book(self, token_id: str) -> tuple[float | None, float | None, dict[str, Any]]:
        """(best bid, best ask, raw book) for a token."""
        raw = self.clob.get_json("book", {"token_id": token_id})
        bids = [float(b["price"]) for b in raw.get("bids") or []]
        asks = [float(a["price"]) for a in raw.get("asks") or []]
        return (max(bids) if bids else None, min(asks) if asks else None, raw)

    def prices_history(
        self, token_id: str, *, interval: str = "1d", fidelity: int = 60
    ) -> list[tuple[datetime, float]]:
        raw = self.clob.get_json(
            "prices-history", {"market": token_id, "interval": interval, "fidelity": fidelity}
        )
        return [
            (datetime.fromtimestamp(int(h["t"]), tz=UTC), float(h["p"]))
            for h in raw.get("history") or []
        ]


# ------------------------------------------------------------ enumeration + matching

#: Gamma tag id for college football game events (slug ``cfb``), seen on every
#: ``cfb-*`` event. ``limit`` is capped at 100 per page; paginate with ``offset``.
CFB_TAG_ID = 100351
PAGE_SIZE = 100


def event_game_start(event: dict[str, Any]) -> datetime | None:
    for market in event.get("markets") or []:
        if start := _game_start(market.get("gameStartTime")):
            return start
    return _game_start(event.get("endDate"))


def iter_game_events(
    client: PolymarketClient,
    *,
    tag_id: int = CFB_TAG_ID,
    prefix: str = CFB_SLUG_PREFIX,
    end_date_min: date | None = None,
) -> list[dict[str, Any]]:
    """Every active, unresolved ``cfb-*`` game event (a few pages of 100)."""
    events: list[dict[str, Any]] = []
    offset = 0
    while True:
        batch = client.gamma.get_json(
            "events",
            {
                "tag_id": tag_id,
                "active": "true",
                "closed": "false",
                "limit": PAGE_SIZE,
                "offset": offset,
                "end_date_min": end_date_min.isoformat() if end_date_min else None,
            },
        )
        events.extend(e for e in batch if (e.get("slug") or "").startswith(prefix))
        if len(batch) < PAGE_SIZE:
            return events
        offset += PAGE_SIZE


def match_event_to_game(event: dict[str, Any], games_by_kickoff: dict[datetime, list[Any]]) -> Any:
    """Pick the ESPN game with the same kickoff whose team locations appear in the title.

    ``games_by_kickoff`` maps a UTC kickoff to ESPN ``Game`` objects. Returns the game or
    ``None`` when no kickoff matches or the names disagree.
    """
    start = event_game_start(event)
    if start is None:
        return None
    title = (event.get("title") or "").lower()
    candidates = games_by_kickoff.get(start.replace(second=0, microsecond=0), [])
    scored = []
    for game in candidates:
        hits = sum(
            1 for loc in (game.home.location, game.away.location) if loc and loc.lower() in title
        )
        if hits:
            scored.append((hits, game))
    if not scored:
        return None
    scored.sort(key=lambda t: t[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None  # ambiguous (e.g. two "Miami" games at the same kickoff)
    return scored[0][1]
