from __future__ import annotations

from datetime import date

from cfb_canes_analytics.matching import match_events, names_agree, normalize


def test_normalize_expands_and_strips() -> None:
    assert normalize("New Mexico St.") == "new mexico state"
    assert normalize("Hawai'i") == "hawaii"
    assert normalize("Texas A&M") == "texas a and m"
    assert normalize("University at Albany") == "albany"


def test_names_agree_on_variants() -> None:
    assert names_agree("Miami (FL)", "Miami")
    assert names_agree("Hawai'i", "Hawaii")
    assert names_agree("Southern University", "Southern")


def test_names_do_not_agree_across_the_two_miamis() -> None:
    """The join that would silently corrupt everything."""
    assert not names_agree("Miami (FL)", "Miami (OH)")
    assert not names_agree("Miami (OH)", "Miami (FL)")


def espn_game(gid: str, d: date, away: str, home: str, aa: str = "", ha: str = "") -> dict:
    return {
        "game_id": gid,
        "game_date_et": d,
        "away_location": away,
        "home_location": home,
        "away_abbr": aa,
        "home_abbr": ha,
    }


def kalshi_event(ticker: str, d: date, away: str, home: str, aa: str = "", ha: str = "") -> dict:
    return {
        "event_ticker": ticker,
        "game_date": d,
        "away_name": away,
        "home_name": home,
        "away": aa,
        "home": ha,
    }


def test_matches_by_name_when_abbreviations_differ() -> None:
    games = [espn_game("1", date(2026, 9, 12), "Louisiana", "USC", "UL", "USC")]
    events = [kalshi_event("K1", date(2026, 9, 12), "Louisiana", "USC", "ULL", "USC")]
    result = match_events(events, games)
    assert result.matched == {"K1": "1"}


def test_matches_across_a_date_boundary() -> None:
    """A late Hawai'i kickoff lands on the next calendar day for one of the sources."""
    games = [espn_game("1", date(2026, 9, 14), "New Mexico State", "Hawaii")]
    events = [kalshi_event("K1", date(2026, 9, 13), "New Mexico St.", "Hawai'i")]
    assert match_events(events, games).matched == {"K1": "1"}


def test_matches_when_kalshi_lists_the_home_team_first() -> None:
    """Kalshi's "Alabama A&M vs Howard" is really Howard at Alabama A&M."""
    games = [espn_game("1", date(2026, 8, 29), "Howard", "Alabama A&M")]
    events = [kalshi_event("K1", date(2026, 8, 29), "Alabama A&M", "Howard")]
    assert match_events(events, games).matched == {"K1": "1"}


def test_alias_bridges_different_spellings() -> None:
    games = [espn_game("1", date(2026, 9, 5), "Chicago State", "UT Martin")]
    events = [kalshi_event("K1", date(2026, 9, 5), "Chicago St.", "Tennessee-Martin")]
    assert match_events(events, games).matched == {"K1": "1"}


def test_unmatched_is_reported_not_guessed() -> None:
    games = [espn_game("1", date(2026, 9, 12), "Ohio State", "Texas")]
    events = [kalshi_event("K1", date(2026, 9, 12), "Alabama", "Georgia")]
    result = match_events(events, games)
    assert result.matched == {} and result.unmatched == ["K1"]


def test_ambiguous_is_reported_not_guessed() -> None:
    games = [
        espn_game("1", date(2026, 9, 12), "Miami", "Duke"),
        espn_game("2", date(2026, 9, 12), "Miami", "Duke"),
    ]
    events = [kalshi_event("K1", date(2026, 9, 12), "Miami", "Duke")]
    result = match_events(events, games)
    assert result.ambiguous == ["K1"] and result.matched == {}
