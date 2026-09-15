"""Capture the *open* market right now: Kalshi ladders, Polymarket O/U, ESPN schedule.

Each run appends rows stamped with ``captured_at``. Run it as often as you like (cron);
the live-decision tooling reads the latest capture per game.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .espn import EspnClient, Game
from .kalshi import TOTAL_SERIES, EventKey, KalshiClient
from .polymarket import (
    PolymarketClient,
    iter_game_events,
    match_event_to_game,
    parse_over_under_markets,
)
from .storage import append_parquet, raw_path, upsert_parquet

logger = logging.getLogger(__name__)


def game_row(game: Game) -> dict[str, Any]:
    return {
        "game_id": game.id,
        "name": game.name,
        "kickoff": game.kickoff,
        "game_date_et": game.game_date_et,
        "season": game.season,
        "week": game.week,
        "status": game.status,
        "completed": game.completed,
        "neutral_site": game.neutral_site,
        "venue": game.venue,
        "indoor": game.indoor,
        "home_id": game.home.id,
        "home_abbr": game.home.abbreviation,
        "home_name": game.home.display_name,
        "home_location": game.home.location,
        "home_score": game.home.score,
        "away_id": game.away.id,
        "away_abbr": game.away.abbreviation,
        "away_name": game.away.display_name,
        "away_location": game.away.location,
        "away_score": game.away.score,
        "total": game.total,
        "odds_provider": game.odds_provider,
        "book_over_under": game.over_under,
        "book_spread": game.spread,
        "fetched_at": datetime.now(UTC),
    }


def snapshot_espn(
    client: EspnClient, base: Path, *, year: int, weeks: list[int] | None
) -> list[Game]:
    """Upsert ESPN games for the given weeks (``None`` = current week). Returns them."""
    games: list[Game] = []
    for week in weeks or [None]:
        shown, batch = client.scoreboard(year, week)
        logger.info("espn: week %s -> %d games", shown, len(batch))
        games.extend(batch)
    n = upsert_parquet(
        raw_path("espn_games.parquet", base), [game_row(g) for g in games], ["game_id"]
    )
    logger.info("espn: %d games stored", n)
    return games


def snapshot_kalshi(client: KalshiClient, base: Path, *, series: str = TOTAL_SERIES) -> int:
    captured_at = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for raw in client.iter_events(series, status="open"):
        key = EventKey.from_event(raw)
        for market in client.get_event_markets(key.event_ticker):
            row = asdict(market)
            row.update(
                captured_at=captured_at,
                game_date=key.game_date,
                away=key.away,
                home=key.home,
                away_name=key.away_name,
                home_name=key.home_name,
            )
            rows.append(row)
    n = append_parquet(raw_path("kalshi_snapshots.parquet", base), rows)
    logger.info("kalshi snapshot: %d markets captured (%d rows stored)", len(rows), n)
    return len(rows)


def snapshot_polymarket(client: PolymarketClient, base: Path, games: list[Game]) -> int:
    """Capture every listed CFB O/U market; attach the ESPN game id when it matches."""
    captured_at = datetime.now(UTC)
    by_kickoff: dict[datetime, list[Game]] = defaultdict(list)
    for game in games:
        by_kickoff[game.kickoff.replace(second=0, microsecond=0)].append(game)

    events = iter_game_events(client, end_date_min=captured_at.date())
    rows: list[dict[str, Any]] = []
    matched = 0
    for event in events:
        game = match_event_to_game(event, by_kickoff)
        matched += game is not None
        for market in parse_over_under_markets(event):
            row = asdict(market)
            row.update(
                captured_at=captured_at,
                game_id=game.id if game else None,
                event_title=event.get("title"),
            )
            rows.append(row)
    n = append_parquet(raw_path("polymarket_snapshots.parquet", base), rows)
    logger.info(
        "polymarket snapshot: %d events (%d matched to ESPN), %d O/U markets (%d rows stored)",
        len(events),
        matched,
        len(rows),
        n,
    )
    return len(rows)
