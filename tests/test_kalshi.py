"""Offline tests for the Kalshi client — fixtures + mock transport, no live calls."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from cfb_canes_analytics.kalshi import (
    Candlestick,
    EventKey,
    KalshiClient,
    KalshiError,
    Market,
    parse_event_ticker,
    price_as_of,
)
from tests.helpers import load


def make_client(handler, **kwargs) -> KalshiClient:
    transport = httpx.MockTransport(handler)
    return KalshiClient(client=httpx.Client(transport=transport), min_interval=0.0, **kwargs)


# --------------------------------------------------------------------------- parsing


def test_parse_event_ticker() -> None:
    assert parse_event_ticker("KXNCAAFTOTAL-26SEP18MIAWAKE") == (
        "KXNCAAFTOTAL",
        date(2026, 9, 18),
        "MIAWAKE",
    )


def test_parse_event_ticker_allows_hyphenated_team_codes() -> None:
    """``M-OH`` (Miami of Ohio) puts a hyphen inside the team blob."""
    series, game_date, teams = parse_event_ticker("KXNCAAFTOTAL-25DEC27M-OHFRES")
    assert series == "KXNCAAFTOTAL"
    assert game_date == date(2025, 12, 27)
    assert teams == "M-OHFRES"


def test_event_key_accepts_2025_at_wording() -> None:
    """2025 events read "A at B" / "Point Total"; 2026 read "A vs B" / "Total Points"."""
    key = EventKey.from_event(
        {
            "event_ticker": "KXNCAAFTOTAL-25DEC27M-OHFRES",
            "sub_title": "M-OH at FRES (Dec 27)",
            "title": "Miami (OH) at Fresno St.: Total Points",
            "series_ticker": "KXNCAAFTOTAL",
        }
    )
    assert key.away == "M-OH" and key.home == "FRES"
    assert key.away_name == "Miami (OH)" and key.home_name == "Fresno St."


def test_event_key_prefers_vs_over_an_at_inside_a_school_name() -> None:
    """ "University at Albany vs Buffalo" must not split on the school's own " at "."""
    key = EventKey.from_event(
        {
            "event_ticker": "KXNCAAFTOTAL-26SEP03ALBBUFF",
            "sub_title": "ALB vs BUFF (Sep 3)",
            "title": "University at Albany vs Buffalo: Total Points",
            "series_ticker": "KXNCAAFTOTAL",
        }
    )
    assert key.away_name == "University at Albany"
    assert key.home_name == "Buffalo"


def test_parse_event_ticker_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_event_ticker("nope")


def test_event_key_splits_away_home_from_sub_title() -> None:
    raw = next(e for e in load("kalshi_events.json")["events"] if "MIAWAKE" in e["event_ticker"])
    key = EventKey.from_event(raw)
    assert key.away == "MIA" and key.home == "WAKE"
    assert key.away_name == "Miami (FL)" and key.home_name == "Wake Forest"
    assert key.game_date == date(2026, 9, 18)
    assert key.series == "KXNCAAFTOTAL"


def test_ladder_markets_parse_strikes() -> None:
    markets = [Market.from_api(m) for m in load("kalshi_markets_ladder.json")["markets"]]
    assert len(markets) == 19
    strikes = sorted(m.floor_strike for m in markets)
    assert strikes[0] == 33.5 and strikes[-1] == 75.5
    m = next(m for m in markets if m.floor_strike == 55.5)
    assert m.ticker.endswith("-56")
    assert m.yes_bid is not None and m.yes_ask is not None and m.yes_bid < m.yes_ask


def test_settled_market_fields() -> None:
    market = Market.from_api(load("kalshi_markets_settled.json")["markets"][0])
    assert market.status == "finalized"
    assert market.settled_yes in (True, False)
    assert market.settlement_value in (0.0, 1.0)
    assert market.close_time is not None and market.close_time.tzinfo is not None


def test_legacy_unsuffixed_fields_are_absent() -> None:
    raw = load("kalshi_markets_ladder.json")["markets"][0]
    assert "last_price" not in raw and "volume" not in raw
    assert "yes_bid_dollars" in raw and "volume_fp" in raw


def test_candlestick_parses_nested_blocks() -> None:
    bar = Candlestick.from_api(load("kalshi_candlesticks.json")["candlesticks"][-1])
    assert bar.yes_bid_close is not None and bar.yes_ask_close is not None
    assert bar.midpoint == pytest.approx((bar.yes_bid_close + bar.yes_ask_close) / 2)
    assert bar.end_ts.tzinfo is not None


def test_midpoint_is_none_without_quotes() -> None:
    bar = Candlestick.from_api({"end_period_ts": 0, "price": {}, "yes_bid": {}, "yes_ask": {}})
    assert bar.midpoint is None and bar.spread is None


# ------------------------------------------------------------------------- price_as_of


def bars_at(*minutes: int) -> list[Candlestick]:
    base = datetime(2026, 9, 18, 22, 0, tzinfo=UTC)
    return [
        Candlestick(
            base + timedelta(minutes=m), None, None, None, m / 100, None, None, None, None, None
        )
        for m in minutes
    ]


def test_price_as_of_spans_sparse_gap() -> None:
    bars = bars_at(0, 10, 20)
    got = price_as_of(bars, datetime(2026, 9, 18, 22, 15, tzinfo=UTC))
    assert got is not None and got.price_close == pytest.approx(0.10)


def test_price_as_of_before_first_bar_is_none() -> None:
    assert price_as_of(bars_at(10), datetime(2026, 9, 18, 22, 5, tzinfo=UTC)) is None


# ---------------------------------------------------------------------------- paging


def test_pagination_follows_cursor_and_stops_on_empty_page() -> None:
    pages = [
        {"markets": [{"ticker": "A"}, {"ticker": "B"}], "cursor": "next"},
        {"markets": [{"ticker": "C"}], "cursor": "again"},
        {"markets": [], "cursor": "again"},
    ]
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("cursor"))
        return httpx.Response(200, json=pages[len(seen) - 1])

    with make_client(handler) as client:
        tickers = [m.ticker for m in client.iter_markets()]
    assert tickers == ["A", "B", "C"]
    assert seen == [None, "next", "again"]


def test_invalid_status_filter_is_rejected_locally() -> None:
    with make_client(lambda r: httpx.Response(200, json={})) as client:
        with pytest.raises(ValueError, match="HTTP 400"):
            list(client.iter_markets(status="active"))


# ---------------------------------------------------------------------------- retries


def test_retries_on_429_then_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json={"markets": [], "cursor": ""})

    with make_client(handler) as client:
        assert list(client.iter_markets()) == []
    assert attempts == 3


def test_retry_delay_honors_header_and_caps() -> None:
    assert KalshiClient.retry_delay(httpx.Response(429, headers={"Retry-After": "7"}), 0) == 7.0
    assert KalshiClient.retry_delay(httpx.Response(429), 3) == 16.0
    assert KalshiClient.retry_delay(httpx.Response(429), 20) == 60.0


def test_raises_after_exhausting_retries() -> None:
    with make_client(lambda r: httpx.Response(429), max_retries=3) as client:
        with pytest.raises(KalshiError, match="HTTP 429"):
            list(client.iter_markets())


def test_does_not_retry_client_errors() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, text="bad request")

    with make_client(handler) as client:
        with pytest.raises(KalshiError, match="HTTP 400"):
            list(client.iter_markets())
    assert calls == 1


def test_candlesticks_chunk_and_dedupe() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(dict(request.url.params))
        start = int(request.url.params["start_ts"])
        return httpx.Response(
            200,
            json={
                "candlesticks": [
                    {"end_period_ts": start, "price": {}, "yes_bid": {}, "yes_ask": {}}
                ]
            },
        )

    start = datetime(2026, 9, 1, tzinfo=UTC)
    with make_client(handler) as client:
        bars = client.get_candlesticks("T", start, start + timedelta(days=5), period_interval=1)
    assert len(requests) == 2  # 5 days of minute bars > 4320-period cap
    assert len(bars) == 2


def test_invalid_period_interval() -> None:
    with make_client(lambda r: httpx.Response(200, json={})) as client:
        with pytest.raises(ValueError, match="period_interval"):
            client.get_candlesticks(
                "T",
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 2, tzinfo=UTC),
                period_interval=5,
            )
