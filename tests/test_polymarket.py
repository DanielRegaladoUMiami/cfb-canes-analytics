from __future__ import annotations

from datetime import UTC, date, datetime

import httpx

from cfb_canes_analytics.polymarket import (
    GAME_TOTAL,
    PolymarketClient,
    classify_question,
    parse_over_under_markets,
    pick_game_event,
)
from tests.helpers import load


def test_parse_over_under_markets_from_fixture() -> None:
    event = load("polymarket_event.json")[0]
    markets = parse_over_under_markets(event, kind=GAME_TOTAL)
    assert [m.line for m in markets] == [50.5, 51.5, 52.5, 53.5]
    assert all(m.kind == GAME_TOTAL for m in markets)
    m = markets[0]
    assert m.event_slug == "cfb-mia-wake-2026-09-18"
    assert m.over_token and m.under_token and m.over_token != m.under_token
    assert m.best_bid is not None and m.best_ask is not None and m.best_bid < m.best_ask
    assert m.game_start == datetime(2026, 9, 18, 23, 30, tzinfo=UTC)
    assert m.over_mark is not None


def test_classify_question_separates_game_total_from_derivatives() -> None:
    assert classify_question("Florida State vs. Alabama: O/U 50.5") == "game_total"
    assert classify_question("Liberty vs. Coastal Carolina: 1H O/U 21.5") == "period_total"
    assert classify_question("Liberty vs. Coastal Carolina: 1Q O/U 10.5") == "period_total"
    assert classify_question("Coastal Carolina 2H Team Total: O/U 14.5") == "team_total"
    assert classify_question("Houston Total Touchdowns: O/U 2.5") == "touchdowns"


def test_only_game_totals_are_kept_when_filtered() -> None:
    event = {
        "slug": "cfb-lib-coast-2026-09-19",
        "markets": [
            {
                "id": "1",
                "question": "Liberty vs. Coastal Carolina: O/U 47.5",
                "line": 47.5,
                "outcomes": '["Over", "Under"]',
                "clobTokenIds": '["a", "b"]',
            },
            {
                "id": "2",
                "question": "Liberty vs. Coastal Carolina: 1H O/U 21.5",
                "line": 21.5,
                "outcomes": '["Over", "Under"]',
                "clobTokenIds": '["c", "d"]',
            },
            {
                "id": "3",
                "question": "Liberty Team Total: O/U 23.5",
                "line": 23.5,
                "outcomes": '["Over", "Under"]',
                "clobTokenIds": '["e", "f"]',
            },
        ],
    }
    assert len(parse_over_under_markets(event)) == 3
    totals = parse_over_under_markets(event, kind=GAME_TOTAL)
    assert [m.line for m in totals] == [47.5]


def test_pick_game_event_filters_by_prefix_and_date() -> None:
    candidates = [
        {"slug": "cbb-mia-wake-2026-01-07"},
        {"slug": "cfb-mia-wake-2026-09-18"},
        {"slug": "cfb-mia-wake-2025-09-18"},
    ]
    assert pick_game_event(candidates, date(2026, 9, 18))["slug"] == "cfb-mia-wake-2026-09-18"
    assert pick_game_event(candidates, date(2026, 9, 19)) is None


def test_book_and_history_parsing() -> None:
    book = load("polymarket_book.json")
    history = load("polymarket_prices_history.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/book"):
            return httpx.Response(200, json=book)
        if request.url.path.endswith("/prices-history"):
            return httpx.Response(200, json=history)
        if request.url.path.endswith("/midpoint"):
            return httpx.Response(200, json={"mid": "0.635"})
        return httpx.Response(404)

    client = PolymarketClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0.0
    )
    bid, ask, _ = client.book("tok")
    assert bid is not None and ask is not None and bid < ask
    assert client.midpoint("tok") == 0.635
    hist = client.prices_history("tok")
    assert len(hist) == 5 and hist[0][0].tzinfo is not None
