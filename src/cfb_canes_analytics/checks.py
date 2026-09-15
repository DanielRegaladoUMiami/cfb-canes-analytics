"""Integrity checks. Every one of these is a thing that would silently poison a model.

Run them after any harvest or snapshot. They answer, in order:

1. Does the Kalshi ladder settle exactly as the ESPN box score says? If a single strike
   disagrees, either the join is wrong or the settlement source is not what the
   documentation claims — and every calibration number built on top would be fiction.
2. Is each ladder monotone in the strike? P(total > k) must fall as k rises. Cent-level
   violations are stale quotes on illiquid strikes and are expected — the survival
   function is fitted with pool-adjacent-violators downstream, which absorbs them. A
   violation of more than ``MAX_LADDER_VIOLATION`` means the ladder is being read
   wrongly (strikes mismatched to prices), which no amount of smoothing would fix, so
   only that fails the check.
3. Is every game matched to ESPN, and is anything ambiguous?

Ladders with no real two-sided quotes are counted as skipped, not failed: an untraded
game has no distribution to check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from .ladder import MIN_USABLE_STRIKES, LadderPoint, usable_points
from .matching import match_events
from .storage import raw_path, read_or_none

#: A ladder inversion bigger than this is a parsing error, not a stale quote.
MAX_LADDER_VIOLATION = 0.10


@dataclass
class CheckResult:
    name: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    examples: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def note(self, message: str, *, limit: int = 5) -> None:
        if len(self.examples) < limit:
            self.examples.append(message)

    def __str__(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        return (
            f"[{status}] {self.name}: {self.passed} ok, {self.failed} bad, {self.skipped} skipped"
        )


def _load(base: Path) -> tuple[pl.DataFrame | None, pl.DataFrame | None, pl.DataFrame | None]:
    return (
        read_or_none(raw_path("kalshi_events.parquet", base)),
        read_or_none(raw_path("kalshi_markets.parquet", base)),
        read_or_none(raw_path("espn_games.parquet", base)),
    )


def check_settlement(base: Path) -> tuple[CheckResult, CheckResult]:
    """Kalshi ``result`` vs the ESPN final score, strike by strike."""
    events, markets, games = _load(base)
    settle = CheckResult("settlement matches ESPN score")
    coverage = CheckResult("games matched to ESPN")
    if events is None or markets is None or games is None:
        settle.note("missing data — run 'cfb harvest' and 'cfb schedule'")
        settle.failed = 1
        return settle, coverage

    live = markets.filter(pl.col("status") != "no_markets")
    tickers = set(live.get_column("event_ticker").to_list())
    event_rows = [e for e in events.to_dicts() if e["event_ticker"] in tickers]
    game_rows = games.to_dicts()
    match = match_events(event_rows, game_rows)

    coverage.passed = len(match.matched)
    coverage.failed = len(match.unmatched)
    coverage.skipped = len(match.ambiguous)
    titles = {e["event_ticker"]: e["title"] for e in event_rows}
    for ticker in match.unmatched:
        coverage.note(f"no ESPN game for {titles.get(ticker, ticker)}")
    for ticker in match.ambiguous:
        coverage.note(f"ambiguous: {titles.get(ticker, ticker)}")

    totals = {g["game_id"]: g["total"] for g in game_rows}
    for market in live.to_dicts():
        game_id = match.matched.get(market["event_ticker"])
        total = totals.get(game_id) if game_id else None
        strike, result = market["floor_strike"], market["result"]
        if total is None or strike is None or result not in ("yes", "no"):
            settle.skipped += 1
            continue
        if (total > strike) == (result == "yes"):
            settle.passed += 1
        else:
            settle.failed += 1
            settle.note(f"{market['ticker']}: scored {total}, strike {strike}, settled {result}")
    return settle, coverage


def worst_violation(points: list[LadderPoint], *, side: str = "mid") -> float:
    """Largest amount by which the ladder rises where it should fall (0 = monotone)."""
    values = [getattr(p, side) for p in points if getattr(p, side) is not None]
    rises = [b - a for a, b in zip(values, values[1:], strict=False)]
    return max([0.0, *rises])


def check_ladders(base: Path, *, tolerance: float = MAX_LADDER_VIOLATION) -> CheckResult:
    """Every snapshot ladder should be non-increasing in the strike."""
    result = CheckResult("ladders monotone in strike")
    snaps = read_or_none(raw_path("kalshi_snapshots.parquet", base))
    if snaps is None:
        result.skipped = 1
        return result
    latest = snaps.sort("captured_at").group_by("ticker", maintain_order=True).last()
    for (event_ticker,), group in latest.group_by(["event_ticker"]):
        points = sorted(
            (
                LadderPoint(r["floor_strike"], r["yes_bid"], r["yes_ask"])
                for r in group.to_dicts()
                if r["floor_strike"] is not None
            ),
            key=lambda p: p.strike,
        )
        quoted = usable_points(points)
        if len(quoted) < MIN_USABLE_STRIKES:
            # A placeholder book (0.08/0.92 on every strike) has nothing to be monotone
            # about; it is reported as unquoted, not as a violation.
            result.skipped += 1
            continue
        violation = worst_violation(quoted)
        if violation <= tolerance:
            result.passed += 1
            if violation > 0:
                result.note(f"{event_ticker} inverted by {violation:.2f} (within tolerance)")
        else:
            result.failed += 1
            result.note(f"{event_ticker} inverted by {violation:.2f}")
    return result


def run_all(base: Path) -> list[CheckResult]:
    settle, coverage = check_settlement(base)
    return [coverage, settle, check_ladders(base)]
