"""Cross-venue comparison: what Kalshi's ladder implies vs what Polymarket charges.

This is **not** a model and makes no claim of predictive edge. It answers one narrow,
checkable question: for a given total line, do the two exchanges quote the same
probability? Kalshi lists ~19 strikes per game, so its ladder interpolates a price at
whatever line Polymarket happens to offer; Polymarket lists one to five lines with a
wider spread. Where they disagree by more than the cost of crossing the spread, one of
them is wrong — that is a place to look, not a bet to place.

Two honest caveats, both reported alongside every row:

- The Kalshi side is only as good as its liquidity. A strike with zero open interest is
  a market maker's quote, not a consensus, so ``kalshi_oi`` is carried through.
- ``edge`` is gross of Kalshi's (quadratic) trading fee. Buying on Polymarket and
  treating Kalshi as fair value still pays the Polymarket ask, which is already netted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import polars as pl

from .ladder import (
    LadderPoint,
    implied_quantile,
    implied_survival,
    is_quoted,
    survival_at,
)
from .polymarket import GAME_TOTAL
from .storage import raw_path, read_or_none


@dataclass(frozen=True, slots=True)
class CrossVenueRow:
    game_id: str | None
    game: str
    kickoff: datetime | None
    line: float
    kalshi_p_over: float
    kalshi_oi: float
    kalshi_median: float
    pm_over_ask: float | None
    pm_over_bid: float | None
    book_total: float | None

    @property
    def buy_over_edge(self) -> float | None:
        """Kalshi's probability minus what Polymarket charges to buy Over."""
        if self.pm_over_ask is None:
            return None
        return self.kalshi_p_over - self.pm_over_ask

    @property
    def buy_under_edge(self) -> float | None:
        """Under costs ``1 - pm_over_bid``; Kalshi says Under is worth ``1 - p_over``."""
        if self.pm_over_bid is None:
            return None
        return self.pm_over_bid - self.kalshi_p_over

    @property
    def best_side(self) -> str | None:
        over, under = self.buy_over_edge, self.buy_under_edge
        if over is None or under is None:
            return None
        if max(over, under) <= 0:
            return None
        return "over" if over >= under else "under"

    @property
    def best_edge(self) -> float:
        return max([e for e in (self.buy_over_edge, self.buy_under_edge) if e is not None] or [0.0])


def latest_snapshot(df: pl.DataFrame | None, keys: list[str]) -> pl.DataFrame | None:
    """Keep only the most recent capture per key."""
    if df is None or df.is_empty():
        return None
    return df.sort("captured_at").group_by(keys, maintain_order=True).last()


def kalshi_ladders(base: Path) -> dict[tuple[str, str], list[LadderPoint]]:
    """(away, home) -> ladder, from the most recent Kalshi snapshot."""
    df = latest_snapshot(read_or_none(raw_path("kalshi_snapshots.parquet", base)), ["ticker"])
    if df is None:
        return {}
    ladders: dict[tuple[str, str], list[LadderPoint]] = {}
    for (away, home), group in df.group_by(["away", "home"]):
        points = [
            LadderPoint(
                strike=row["floor_strike"],
                bid=row["yes_bid"],
                ask=row["yes_ask"],
                volume=row["volume"],
                open_interest=row["open_interest"],
            )
            for row in group.to_dicts()
            if row["floor_strike"] is not None
        ]
        points.sort(key=lambda p: p.strike)
        if points:
            ladders[(away, home)] = points
    return ladders


def _abbr_key(row: dict) -> tuple[str, str]:
    return (row["away_abbr"], row["home_abbr"])


def build_rows(base: Path, *, min_open_interest: float = 0.0) -> list[CrossVenueRow]:
    games = read_or_none(raw_path("espn_games.parquet", base))
    pm = latest_snapshot(
        read_or_none(raw_path("polymarket_snapshots.parquet", base)), ["market_id"]
    )
    if games is None or pm is None:
        return []
    ladders = kalshi_ladders(base)
    kalshi_by_abbr = {}
    for (away, home), points in ladders.items():
        kalshi_by_abbr[(away, home)] = points

    games_by_id = {g["game_id"]: g for g in games.to_dicts()}
    rows: list[CrossVenueRow] = []
    wanted = pm.filter(pl.col("game_id").is_not_null() & (pl.col("kind") == GAME_TOTAL))
    for market in wanted.to_dicts():
        game = games_by_id.get(market["game_id"])
        if game is None or game["completed"]:
            continue
        points = kalshi_by_abbr.get(_abbr_key(game))
        if not points:
            continue
        surv = implied_survival(points)
        if not surv:
            continue
        line = market["line"]
        quoted = [p for p in points if is_quoted(p)]
        if not quoted:
            continue
        nearest = min(quoted, key=lambda p: abs(p.strike - line))
        oi = nearest.open_interest or 0.0
        if oi < min_open_interest:
            continue
        rows.append(
            CrossVenueRow(
                game_id=game["game_id"],
                game=game["name"],
                kickoff=game["kickoff"],
                line=line,
                kalshi_p_over=survival_at(surv, line),
                kalshi_oi=oi,
                kalshi_median=implied_quantile(surv, 0.5),
                pm_over_ask=market["best_ask"],
                pm_over_bid=market["best_bid"],
                book_total=game["book_over_under"],
            )
        )
    rows.sort(key=lambda r: r.best_edge, reverse=True)
    return rows


def disagreements(rows: list[CrossVenueRow], *, threshold: float = 0.05) -> list[CrossVenueRow]:
    return [r for r in rows if r.best_side is not None and r.best_edge >= threshold]
