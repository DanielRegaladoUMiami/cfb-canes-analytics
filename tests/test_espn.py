from __future__ import annotations

from datetime import date

from cfb_canes_analytics.espn import parse_scoreboard
from tests.helpers import load


def test_parse_scoreboard_fixture() -> None:
    week, games = parse_scoreboard(load("espn_scoreboard.json"))
    assert week == 2
    assert len(games) == 2
    famu = next(g for g in games if "Florida A&M" in g.name)
    assert famu.home.abbreviation == "MIA" and famu.away.abbreviation == "FAMU"
    assert famu.completed and famu.total == 84
    assert famu.kickoff.tzinfo is not None
    assert famu.game_date_et == date(2026, 9, 10)  # 00:00Z on the 11th is the 10th in Miami
    assert famu.indoor is False
    assert famu.season == 2026 and famu.week == 2
