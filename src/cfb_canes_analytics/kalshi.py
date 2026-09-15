"""Client for Kalshi's public ``trade-api/v2`` market-data endpoints (NCAA football).

Ported from mlb-canes-analytics. No authentication is required for market data.

Behaviours verified empirically (2026-07-26 on MLB, re-checked 2026-09-14 on NCAAF):

- Numeric fields carry ``_dollars`` (string decimals) or ``_fp`` suffixes; the legacy
  unsuffixed names are absent, so ``raw.get("volume")`` silently yields ``None``.
- ``period_interval`` accepts only 1, 60 and 1440; more than ~5000 periods per request
  returns HTTP 400.
- ``status=settled`` is the filter; settled markets report ``status == "finalized"``.
  ``active`` and ``finalized`` as filters return HTTP 400.
- A settled market's own bid/ask collapse to 0.00/1.00; live quotes come from candles.
- Candlestick bars are sparse (only periods with activity); use last-bar-at-or-before.
- Events are retained far longer than their markets. 2025-season NCAAF events exist as
  shells with zero markets; only the current rolling window has prices.
- Event tickers encode the game as ``<SERIES>-<YY><MON><DD><AWAY><HOME>`` where the date
  is the US-Eastern game date and the two team codes are concatenated without a
  separator. Team codes may contain a hyphen (``M-OH`` = Miami of Ohio), so the ticker
  alone cannot be split; the event ``sub_title`` (``"MIA vs WAKE (Sep 18)"``) is the
  reliable source. Away team first in both the ticker and the title.
- Kalshi changed wording between seasons: 2025 events read ``"MIA at WAKE"`` /
  ``"... : Point Total"``, 2026 events read ``"MIA vs WAKE"`` / ``"... : Total Points"``.
  Both separators must be accepted, and ``vs`` must be tried first: a school name can
  itself contain " at " ("University at Albany vs Buffalo"), so splitting on the first
  " at " yields the nonsense pair ("University", "Albany vs Buffalo").
- Totals markets carry ``floor_strike`` (e.g. 55.5 for "Over 55.5 points scored"); the
  market ticker suffix is the rounded strike (``-56``).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ._http import ApiError, RetryingClient

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

TOTAL_SERIES = "KXNCAAFTOTAL"
GAME_SERIES = "KXNCAAFGAME"
SPREAD_SERIES = "KXNCAAFSPREAD"

#: Verified: 5 and 30 return HTTP 400.
VALID_PERIOD_INTERVALS = frozenset({1, 60, 1440})

#: Accepted values for the ``status`` query filter (``active``/``finalized`` -> 400).
VALID_STATUS_FILTERS = frozenset({"open", "closed", "settled", "unopened"})

#: 4320 minute bars (72h) verified to work; 6000 verified to fail.
MAX_PERIODS_PER_REQUEST = 4320

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}  # fmt: skip
_EVENT_TICKER = re.compile(
    r"^(?P<series>[A-Z0-9]+)-(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})(?P<teams>[A-Z0-9-]+)$"
)
_SUB_TITLES = [
    re.compile(
        rf"^(?P<away>\S+) {sep} (?P<home>\S+) \((?P<mon>[A-Za-z]{{3}}) (?P<day>\d{{1,2}})\)$"
    )
    for sep in ("vs", "at")
]
_TITLES = [re.compile(rf"^(?P<away>.+?) {sep} (?P<home>.+?)(?::.*)?$") for sep in ("vs", "at")]


def _first_match(patterns: list[re.Pattern[str]], text: str) -> re.Match[str] | None:
    """Try each separator in order; ``vs`` wins over ``at`` (see module docstring)."""
    for pattern in patterns:
        if match := pattern.match(text):
            return match
    return None


KalshiError = ApiError


def _dollars(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _fp(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def parse_event_ticker(event_ticker: str) -> tuple[str, date, str]:
    """Split ``KXNCAAFTOTAL-26SEP18MIAWAKE`` into (series, game date, team blob).

    The team blob is ``AWAY + HOME`` with no separator, and team codes may themselves
    contain a hyphen (``M-OH``), so it cannot be split reliably here. Use
    :class:`EventKey`, which reads the event sub_title, to get the two codes.
    """
    match = _EVENT_TICKER.match(event_ticker)
    if not match:
        raise ValueError(f"unrecognised event ticker: {event_ticker!r}")
    game_date = date(2000 + int(match["yy"]), _MONTHS[match["mon"]], int(match["dd"]))
    return match["series"], game_date, match["teams"]


@dataclass(frozen=True, slots=True)
class EventKey:
    """One game as Kalshi identifies it. ``away``/``home`` are Kalshi team codes."""

    event_ticker: str
    series: str
    game_date: date
    away: str | None
    home: str | None
    away_name: str | None
    home_name: str | None
    title: str
    sub_title: str

    @classmethod
    def from_event(cls, raw: dict[str, Any]) -> EventKey:
        ticker = raw["event_ticker"]
        series, game_date, _ = parse_event_ticker(ticker)
        sub_title = raw.get("sub_title") or ""
        title = raw.get("title") or ""
        away = home = away_name = home_name = None
        if m := _first_match(_SUB_TITLES, sub_title):
            away, home = m["away"], m["home"]
        if m := _first_match(_TITLES, title):
            away_name, home_name = m["away"].strip(), m["home"].strip()
        return cls(
            event_ticker=ticker,
            series=raw.get("series_ticker") or series,
            game_date=game_date,
            away=away,
            home=home,
            away_name=away_name,
            home_name=home_name,
            title=title,
            sub_title=sub_title,
        )


@dataclass(frozen=True, slots=True)
class Market:
    """A single Kalshi market. A totals event has one per strike."""

    ticker: str
    event_ticker: str
    title: str
    yes_sub_title: str
    status: str
    result: str
    floor_strike: float | None
    cap_strike: float | None
    open_time: datetime | None
    close_time: datetime | None
    expiration_time: datetime | None
    last_price: float | None
    yes_bid: float | None
    yes_ask: float | None
    volume: float | None
    open_interest: float | None
    liquidity: float | None
    settlement_value: float | None

    @property
    def settled_yes(self) -> bool | None:
        if self.result == "yes":
            return True
        if self.result == "no":
            return False
        return None

    @property
    def midpoint(self) -> float | None:
        if self.yes_bid is None or self.yes_ask is None:
            return None
        return (self.yes_bid + self.yes_ask) / 2

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Market:
        return cls(
            ticker=raw["ticker"],
            event_ticker=raw.get("event_ticker", ""),
            title=raw.get("title", ""),
            yes_sub_title=raw.get("yes_sub_title", ""),
            status=raw.get("status", ""),
            result=raw.get("result", ""),
            floor_strike=_number(raw.get("floor_strike")),
            cap_strike=_number(raw.get("cap_strike")),
            open_time=_timestamp(raw.get("open_time")),
            close_time=_timestamp(raw.get("close_time")),
            expiration_time=_timestamp(raw.get("expiration_time")),
            last_price=_dollars(raw.get("last_price_dollars")),
            yes_bid=_dollars(raw.get("yes_bid_dollars")),
            yes_ask=_dollars(raw.get("yes_ask_dollars")),
            volume=_fp(raw.get("volume_fp")),
            open_interest=_fp(raw.get("open_interest_fp")),
            liquidity=_dollars(raw.get("liquidity_dollars")),
            settlement_value=_dollars(raw.get("settlement_value_dollars")),
        )


@dataclass(frozen=True, slots=True)
class Candlestick:
    """One OHLC bar. Prices are probabilities in [0, 1]."""

    end_ts: datetime
    price_open: float | None
    price_high: float | None
    price_low: float | None
    price_close: float | None
    price_mean: float | None
    yes_bid_close: float | None
    yes_ask_close: float | None
    volume: float | None
    open_interest: float | None

    @property
    def midpoint(self) -> float | None:
        """Bid/ask midpoint: the near-vig-free probability. Do not de-vig again."""
        if self.yes_bid_close is None or self.yes_ask_close is None:
            return None
        return (self.yes_bid_close + self.yes_ask_close) / 2

    @property
    def spread(self) -> float | None:
        if self.yes_bid_close is None or self.yes_ask_close is None:
            return None
        return self.yes_ask_close - self.yes_bid_close

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Candlestick:
        price = raw.get("price") or {}
        bid = raw.get("yes_bid") or {}
        ask = raw.get("yes_ask") or {}
        return cls(
            end_ts=datetime.fromtimestamp(raw["end_period_ts"], tz=UTC),
            price_open=_dollars(price.get("open_dollars")),
            price_high=_dollars(price.get("high_dollars")),
            price_low=_dollars(price.get("low_dollars")),
            price_close=_dollars(price.get("close_dollars")),
            price_mean=_dollars(price.get("mean_dollars")),
            yes_bid_close=_dollars(bid.get("close_dollars")),
            yes_ask_close=_dollars(ask.get("close_dollars")),
            volume=_fp(raw.get("volume_fp")),
            open_interest=_fp(raw.get("open_interest_fp")),
        )


class KalshiClient(RetryingClient):
    """Rate-limit-aware client for Kalshi market data."""

    def __init__(self, base_url: str = BASE_URL, **kwargs: Any) -> None:
        super().__init__(base_url, **kwargs)

    def _paginate(self, path: str, params: dict[str, Any], key: str) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        while True:
            page = self.get_json(path, {**params, "cursor": cursor})
            items = page.get(key) or []
            yield from items
            cursor = page.get("cursor") or None
            # Kalshi returns a cursor on the final page too; an empty page ends it.
            if not cursor or not items:
                return

    @staticmethod
    def _check_status(status: str | None) -> None:
        if status is not None and status not in VALID_STATUS_FILTERS:
            raise ValueError(
                f"status={status!r} is rejected by the API with HTTP 400. "
                f"Valid values: {sorted(VALID_STATUS_FILTERS)}"
            )

    def iter_events(
        self, series_ticker: str = TOTAL_SERIES, *, status: str | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield raw event records for a series (shells persist beyond retention)."""
        self._check_status(status)
        yield from self._paginate(
            "events", {"series_ticker": series_ticker, "status": status, "limit": 200}, "events"
        )

    def get_event(self, event_ticker: str) -> dict[str, Any]:
        page = self.get_json(f"events/{event_ticker}", {"with_nested_markets": "false"})
        return page.get("event") or page

    def iter_markets(
        self, series_ticker: str = TOTAL_SERIES, *, status: str | None = None
    ) -> Iterator[Market]:
        self._check_status(status)
        params = {"series_ticker": series_ticker, "limit": 1000, "status": status}
        for raw in self._paginate("markets", params, "markets"):
            yield Market.from_api(raw)

    def get_event_markets(self, event_ticker: str) -> list[Market]:
        """Markets for one event; empty for events outside the retention window."""
        page = self.get_json("markets", {"event_ticker": event_ticker, "limit": 200})
        return [Market.from_api(raw) for raw in page.get("markets") or []]

    def get_candlesticks(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        *,
        period_interval: int = 1,
        series_ticker: str = TOTAL_SERIES,
    ) -> list[Candlestick]:
        """Candlesticks for a market, chunked to stay under the period cap."""
        if period_interval not in VALID_PERIOD_INTERVALS:
            raise ValueError(
                f"period_interval={period_interval} is rejected by the API with HTTP 400. "
                f"Valid values: {sorted(VALID_PERIOD_INTERVALS)}"
            )
        if end < start:
            raise ValueError(f"end ({end}) precedes start ({start})")

        chunk = timedelta(minutes=period_interval * MAX_PERIODS_PER_REQUEST)
        bars: list[Candlestick] = []
        seen: set[int] = set()
        window_start = start
        while window_start < end:
            window_end = min(window_start + chunk, end)
            page = self.get_json(
                f"series/{series_ticker}/markets/{ticker}/candlesticks",
                {
                    "start_ts": int(window_start.timestamp()),
                    "end_ts": int(window_end.timestamp()),
                    "period_interval": period_interval,
                },
            )
            for raw in page.get("candlesticks") or []:
                if raw["end_period_ts"] in seen:
                    continue
                seen.add(raw["end_period_ts"])
                bars.append(Candlestick.from_api(raw))
            window_start = window_end
        bars.sort(key=lambda bar: bar.end_ts)
        return bars


def price_as_of(bars: list[Candlestick], instant: datetime) -> Candlestick | None:
    """Last bar at or before ``instant`` (bars are sparse, so never index exactly)."""
    candidate: Candlestick | None = None
    for bar in bars:
        if bar.end_ts > instant:
            break
        candidate = bar
    return candidate
