"""Harvest every retained Kalshi totals market into parquet. Time-critical, resumable.

Kalshi keeps settled markets for a rolling window only, so this is the one job that
must never fall behind. Three phases, each idempotent:

1. events   — settled/closed event shells -> ``kalshi_events.parquet``
2. markets  — the strike ladder per event   -> ``kalshi_markets.parquet``
3. candles  — hourly bars over each market's life and minute bars for the hours before
              close -> ``kalshi_candles_60.parquet`` / ``kalshi_candles_1.parquet``,
              with ``kalshi_candles_log.parquet`` recording what was fetched (including
              markets that returned zero bars, so they are not re-fetched forever).

Settled markets close at the *end* of the game (in-game trading is allowed), so the
minute window is wide enough to reach back past kickoff.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from .kalshi import TOTAL_SERIES, Candlestick, EventKey, KalshiClient, Market
from .storage import existing_values, raw_path, read_or_none, upsert_parquet

logger = logging.getLogger(__name__)

MINUTE_WINDOW = timedelta(hours=8)
PAD = timedelta(minutes=5)

#: Markets per flush. Each flush rewrites the whole parquet file (an upsert, so the job
#: stays idempotent and resumable), and the candle tables run to millions of rows, so a
#: small batch means quadratic I/O. 250 keeps at most a few minutes of work at risk.
MARKET_BATCH = 50
CANDLE_BATCH = 250


def event_row(raw: dict[str, Any], status: str | None = None) -> dict[str, Any]:
    key = EventKey.from_event(raw)
    row = asdict(key)
    row["status_filter"] = status
    row["harvested_at"] = datetime.now(UTC)
    return row


def market_row(market: Market) -> dict[str, Any]:
    row = asdict(market)
    row["harvested_at"] = datetime.now(UTC)
    return row


def candle_row(ticker: str, interval: int, bar: Candlestick) -> dict[str, Any]:
    row = asdict(bar)
    row["ticker"] = ticker
    row["interval"] = interval
    return row


def harvest_events(
    client: KalshiClient, base: Path, *, series: str = TOTAL_SERIES, statuses=("settled", "closed")
) -> int:
    rows: list[dict[str, Any]] = []
    for status in statuses:
        for raw in client.iter_events(series, status=status):
            rows.append(event_row(raw, status))
    n = upsert_parquet(raw_path("kalshi_events.parquet", base), rows, ["event_ticker"])
    logger.info("events: %d fetched, %d stored", len(rows), n)
    return n


def harvest_markets(client: KalshiClient, base: Path) -> int:
    events = read_or_none(raw_path("kalshi_events.parquet", base))
    if events is None:
        return 0
    markets_path = raw_path("kalshi_markets.parquet", base)
    done = existing_values(markets_path, "event_ticker")
    todo = [t for t in events.get_column("event_ticker").to_list() if t not in done]
    logger.info("markets: %d events to fetch (%d already stored)", len(todo), len(done))
    rows: list[dict[str, Any]] = []
    fetched = 0
    for i, event_ticker in enumerate(todo, 1):
        markets = client.get_event_markets(event_ticker)
        if not markets:
            # Outside the retention window: record a tombstone so we do not retry daily.
            rows.append(
                {
                    "ticker": f"{event_ticker}-EMPTY",
                    "event_ticker": event_ticker,
                    "status": "no_markets",
                    "harvested_at": datetime.now(UTC),
                }
            )
        rows.extend(market_row(m) for m in markets)
        fetched += len(markets)
        if i % MARKET_BATCH == 0 or i == len(todo):
            upsert_parquet(markets_path, rows, ["ticker"])
            logger.info("markets: %d/%d events, %d markets", i, len(todo), fetched)
            rows = []
    return fetched


def _candle_window(market: dict[str, Any], interval: int) -> tuple[datetime, datetime] | None:
    close = market.get("close_time")
    if close is None:
        return None
    if interval == 1:
        return close - MINUTE_WINDOW, close + PAD
    open_ = market.get("open_time") or (close - timedelta(days=14))
    return open_ - PAD, close + PAD


def harvest_candles(
    client: KalshiClient, base: Path, *, interval: int = 60, series: str = TOTAL_SERIES
) -> int:
    markets = read_or_none(raw_path("kalshi_markets.parquet", base))
    if markets is None:
        return 0
    markets = markets.filter(pl.col("status") != "no_markets")
    log_path = raw_path("kalshi_candles_log.parquet", base)
    log = read_or_none(log_path)
    done: set[str] = set()
    if log is not None:
        done = set(log.filter(pl.col("interval") == interval).get_column("ticker").to_list())
    todo = [m for m in markets.to_dicts() if m["ticker"] not in done]
    logger.info("candles[%d]: %d markets to fetch (%d done)", interval, len(todo), len(done))
    candles_path = raw_path(f"kalshi_candles_{interval}.parquet", base)
    rows: list[dict[str, Any]] = []
    log_rows: list[dict[str, Any]] = []
    total = 0
    for i, m in enumerate(todo, 1):
        window = _candle_window(m, interval)
        if window is None:
            continue
        bars = client.get_candlesticks(
            m["ticker"], window[0], window[1], period_interval=interval, series_ticker=series
        )
        rows.extend(candle_row(m["ticker"], interval, b) for b in bars)
        log_rows.append(
            {
                "ticker": m["ticker"],
                "interval": interval,
                "n_bars": len(bars),
                "window_start": window[0],
                "window_end": window[1],
                "harvested_at": datetime.now(UTC),
            }
        )
        total += len(bars)
        if i % CANDLE_BATCH == 0 or i == len(todo):
            upsert_parquet(candles_path, rows, ["ticker", "interval", "end_ts"])
            upsert_parquet(log_path, log_rows, ["ticker", "interval"])
            logger.info("candles[%d]: %d/%d markets, %d bars", interval, i, len(todo), total)
            rows, log_rows = [], []
    return total


def harvest_all(
    client: KalshiClient, base: Path, *, series: str = TOTAL_SERIES, intervals=(60, 1)
) -> dict[str, int]:
    out = {"events": harvest_events(client, base, series=series)}
    out["markets"] = harvest_markets(client, base)
    for interval in intervals:
        out[f"candles_{interval}"] = harvest_candles(client, base, interval=interval, series=series)
    return out
