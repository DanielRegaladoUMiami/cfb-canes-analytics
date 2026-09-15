"""Turn a strike ladder into an implied distribution of total points.

Each Kalshi totals market prices ``P(total > strike)``. Read across strikes and the
midpoints form the market's implied survival function S(k). Small violations of
monotonicity appear from stale quotes on illiquid strikes, so we pool-adjacent-violators
the sequence before interpolating. Beyond the first and last strike we assume S goes to
1 and 0 linearly over ``TAIL_WIDTH`` points — a stated modelling choice, revisit once
the ladder calibration study (v0.2) says otherwise.

**A quote is not always a price.** On a game nobody is trading, Kalshi shows a
placeholder book — verified 2026-09-14 on ``KXNCAAFTOTAL-26SEP19UTMMEM``, where 16 of 19
strikes read exactly ``0.08 / 0.92`` with zero open interest. Those midpoints are all
0.50, so reading them naively yields an "implied distribution" that says every total
from 36 to 78 is a coin flip. Any strike whose spread exceeds ``MAX_SPREAD`` is
therefore dropped before fitting, and a ladder with too few survivors has no implied
distribution at all rather than a fictional one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .kalshi import Market

TAIL_WIDTH = 10.0

#: Widest bid/ask that still counts as a real quote. Kalshi's placeholder book is
#: 0.08/0.92 (a spread of 0.84); genuine quotes on traded strikes run 0.01-0.10, and
#: thin-but-real ones up to about 0.20.
MAX_SPREAD = 0.25

#: Fewer usable strikes than this and the ladder cannot describe a distribution.
MIN_USABLE_STRIKES = 3


@dataclass(frozen=True, slots=True)
class LadderPoint:
    strike: float
    bid: float | None
    ask: float | None
    volume: float | None = None
    open_interest: float | None = None

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid


def ladder_from_markets(markets: Iterable[Market]) -> list[LadderPoint]:
    points = [
        LadderPoint(
            strike=m.floor_strike,
            bid=m.yes_bid,
            ask=m.yes_ask,
            volume=m.volume,
            open_interest=m.open_interest,
        )
        for m in markets
        if m.floor_strike is not None
    ]
    points.sort(key=lambda p: p.strike)
    return points


def pav_nonincreasing(values: Sequence[float]) -> list[float]:
    """Pool-adjacent-violators projection onto non-increasing sequences (L2)."""
    blocks: list[list[float]] = []  # [mean, count]
    for value in values:
        blocks.append([float(value), 1.0])
        while len(blocks) >= 2 and blocks[-2][0] < blocks[-1][0]:
            m2, c2 = blocks.pop()
            m1, c1 = blocks.pop()
            blocks.append([(m1 * c1 + m2 * c2) / (c1 + c2), c1 + c2])
    out: list[float] = []
    for mean, count in blocks:
        out.extend([mean] * int(count))
    return out


def is_quoted(point: LadderPoint, *, max_spread: float = MAX_SPREAD) -> bool:
    """Whether this strike carries a real two-sided quote rather than a placeholder."""
    spread = point.spread
    return spread is not None and spread <= max_spread


def usable_points(
    points: Sequence[LadderPoint], *, max_spread: float = MAX_SPREAD
) -> list[LadderPoint]:
    return [p for p in points if is_quoted(p, max_spread=max_spread)]


def implied_survival(
    points: Sequence[LadderPoint],
    *,
    side: str = "mid",
    max_spread: float = MAX_SPREAD,
    min_strikes: int = MIN_USABLE_STRIKES,
) -> list[tuple[float, float]]:
    """Monotone (strike, P(total > strike)) pairs from ``mid``, ``bid`` or ``ask``.

    Returns an empty list when the ladder has too few genuinely quoted strikes — an
    empty answer is correct, a fabricated distribution is not.
    """
    quoted = usable_points(points, max_spread=max_spread)
    if len(quoted) < min_strikes:
        return []
    usable = [(p.strike, getattr(p, side)) for p in quoted if getattr(p, side) is not None]
    if not usable:
        return []
    strikes = [s for s, _ in usable]
    probs = pav_nonincreasing([min(max(p, 0.0), 1.0) for _, p in usable])
    return list(zip(strikes, probs, strict=True))


def _extended(
    surv: Sequence[tuple[float, float]], tail_width: float
) -> tuple[list[float], list[float]]:
    xs = [s for s, _ in surv]
    ps = [p for _, p in surv]
    return [xs[0] - tail_width, *xs, xs[-1] + tail_width], [1.0, *ps, 0.0]


def survival_at(
    surv: Sequence[tuple[float, float]], x: float, *, tail_width: float = TAIL_WIDTH
) -> float:
    """Interpolated P(total > x)."""
    if not surv:
        raise ValueError("empty survival function")
    xs, ps = _extended(surv, tail_width)
    if x <= xs[0]:
        return 1.0
    if x >= xs[-1]:
        return 0.0
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            if xs[i + 1] == xs[i]:
                return ps[i]
            w = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ps[i] + (ps[i + 1] - ps[i]) * w
    return 0.0


def implied_quantile(
    surv: Sequence[tuple[float, float]], q: float, *, tail_width: float = TAIL_WIDTH
) -> float:
    """Total x such that P(total <= x) = q (q=0.5 is the implied median total)."""
    if not surv:
        raise ValueError("empty survival function")
    target = 1.0 - q
    xs, ps = _extended(surv, tail_width)
    for i in range(len(xs) - 1):
        p0, p1 = ps[i], ps[i + 1]
        if p0 >= target >= p1:
            if p0 == p1:
                return (xs[i] + xs[i + 1]) / 2
            return xs[i] + (xs[i + 1] - xs[i]) * (p0 - target) / (p0 - p1)
    return xs[-1]


def implied_mean(surv: Sequence[tuple[float, float]], *, tail_width: float = TAIL_WIDTH) -> float:
    """E[total] = integral of S(x) dx from 0, trapezoidal over the extended ladder."""
    if not surv:
        raise ValueError("empty survival function")
    xs, ps = _extended(surv, tail_width)
    total = max(xs[0], 0.0)  # S = 1 below the first anchor
    for i in range(len(xs) - 1):
        total += (xs[i + 1] - xs[i]) * (ps[i] + ps[i + 1]) / 2
    return total


def prob_over(
    points: Sequence[LadderPoint],
    line: float,
    *,
    side: str = "mid",
    tail_width: float = TAIL_WIDTH,
) -> float | None:
    """Ladder-implied P(total > line) — comparable to a sportsbook/Polymarket O/U line."""
    surv = implied_survival(points, side=side)
    if not surv:
        return None
    return survival_at(surv, line, tail_width=tail_width)


def is_monotone(points: Sequence[LadderPoint], *, side: str = "mid", tol: float = 0.0) -> bool:
    values = [getattr(p, side) for p in points if getattr(p, side) is not None]
    return all(b <= a + tol for a, b in zip(values, values[1:], strict=False))
