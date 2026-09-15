from __future__ import annotations

import pytest

from cfb_canes_analytics.checks import worst_violation
from cfb_canes_analytics.ladder import LadderPoint


def ladder(*mids: float) -> list[LadderPoint]:
    return [LadderPoint(40.5 + i, m, m) for i, m in enumerate(mids)]


def test_monotone_ladder_has_no_violation() -> None:
    assert worst_violation(ladder(0.9, 0.7, 0.5, 0.2)) == 0.0


def test_violation_is_the_largest_upward_step() -> None:
    assert worst_violation(ladder(0.9, 0.7, 0.75, 0.5)) == pytest.approx(0.05)


def test_empty_ladder_has_no_violation() -> None:
    assert worst_violation([]) == 0.0


def test_missing_quotes_are_ignored() -> None:
    points = [
        LadderPoint(40.5, 0.9, 0.9),
        LadderPoint(41.5, None, None),
        LadderPoint(42.5, 0.5, 0.5),
    ]
    assert worst_violation(points) == 0.0
