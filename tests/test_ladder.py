from __future__ import annotations

import pytest

from cfb_canes_analytics.kalshi import Market
from cfb_canes_analytics.ladder import (
    LadderPoint,
    implied_mean,
    implied_quantile,
    implied_survival,
    is_monotone,
    ladder_from_markets,
    pav_nonincreasing,
    prob_over,
    survival_at,
)
from tests.helpers import load


def synthetic() -> list[LadderPoint]:
    # S(k) falls linearly from 0.9 at 40.5 to 0.1 at 60.5 -> median at 50.5
    return [
        LadderPoint(40.5 + 2 * i, 0.9 - 0.08 * i - 0.01, 0.9 - 0.08 * i + 0.01) for i in range(11)
    ]


def test_pav_projects_onto_nonincreasing() -> None:
    assert pav_nonincreasing([0.9, 0.7, 0.75, 0.5]) == pytest.approx([0.9, 0.725, 0.725, 0.5])
    assert pav_nonincreasing([0.5, 0.4, 0.3]) == [0.5, 0.4, 0.3]


def test_implied_median_of_linear_ladder() -> None:
    surv = implied_survival(synthetic())
    assert implied_quantile(surv, 0.5) == pytest.approx(50.5, abs=1e-6)
    assert survival_at(surv, 50.5) == pytest.approx(0.5, abs=1e-6)
    assert prob_over(synthetic(), 44.5) == pytest.approx(0.74, abs=1e-6)


def test_tails_and_mean() -> None:
    surv = implied_survival(synthetic())
    assert survival_at(surv, 0) == 1.0
    assert survival_at(surv, 500) == 0.0
    mean = implied_mean(surv)
    assert 48 < mean < 53


def test_real_ladder_fixture_is_sensible() -> None:
    points = ladder_from_markets(
        Market.from_api(m) for m in load("kalshi_markets_ladder.json")["markets"]
    )
    assert [p.strike for p in points] == sorted(p.strike for p in points)
    surv = implied_survival(points)
    assert is_monotone([LadderPoint(s, p, p) for s, p in surv])
    median = implied_quantile(surv, 0.5)
    assert 45 < median < 65  # Miami at Wake Forest was priced around 54-55


def test_empty_ladder() -> None:
    assert implied_survival([]) == []
    assert prob_over([], 50) is None
