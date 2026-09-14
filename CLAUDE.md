# CFB Canes Analytics

## Goal

Totals (over/under) model for FBS college football. The output is a calibrated
distribution of total points per game, priced against exchange strike ladders (Kalshi
`KXNCAAFTOTAL`, Polymarket per-game O/U markets) and benchmarked to sportsbook closing
totals. Execution venues: Kalshi, Polymarket, Hard Rock Bet (manual, no API).

The objective is **not** "pick over or under." It is: beat the market's implied
distribution out-of-sample, measured by CLV against the exchange close and by ROI net of
fees. No real-money claims until paper trading shows CLV over several weeks.

## Data landscape (verified 2026-09-14)

### Kalshi (prices — time-critical)

- Base URL `https://api.elections.kalshi.com/trade-api/v2`. No auth for market data.
- Series: `KXNCAAFTOTAL` (totals), `KXNCAAFGAME` (winner), `KXNCAAFSPREAD` (spread).
- Event ticker encodes the game: `KXNCAAFTOTAL-26SEP18MIAWAKE` = 2026-09-18, **AWAY**
  `MIA`, **HOME** `WAKE`. Titles read "Away vs Home". Market ticker appends the strike:
  `...-56` for `floor_strike = 55.5` ("Over 55.5 points scored").
- ~19 strikes per game. Each market's yes bid/ask is P(total > strike). The ladder is the
  market's implied survival function; it must be monotone in the strike.
- **Retention is a rolling window.** 5,437 settled markets across 301 games retained on
  2026-09-14, oldest close 2026-08-28 (season week 1). 2025-season events exist as
  shells with zero markets. Forward-only; the window length is not yet known.
- Settlement source is ESPN. `result` is `yes`/`no`, `status` reads `finalized`.
- Candlesticks: `period_interval` in {1, 60, 1440}; max ~4320 periods per request; bars
  are sparse (only periods with activity). Use last-bar-at-or-before for a cutoff.
- API gotchas (inherited from mlb-canes-analytics): numeric fields use `_dollars` /
  `_fp` suffixes and the legacy names are absent; `status=active|finalized` as a filter
  returns 400 (use `settled`/`closed`/`unopened`); 429s arrive fast, back off.
- Fees are **quadratic** in price, not a flat percentage. Net every ROI figure.

### Polymarket (prices)

- Gamma: `https://gamma-api.polymarket.com/events?slug=cfb-<away>-<home>-<YYYY-MM-DD>`
  (e.g. `cfb-mia-wake-2026-09-18`). Search: `/public-search?q=`. Team slugs are
  Polymarket's own (`flst` = Florida State), so keep an alias table.
- O/U markets have `question` "A vs. B: O/U 51.5", `line`, `outcomes` ["Over","Under"],
  `outcomePrices`, `bestBid`, `bestAsk`, `clobTokenIds` (Over token first),
  `gameStartTime`. Several lines per game.
- CLOB (`https://clob.polymarket.com`): `/midpoint?token_id=`, `/book?token_id=`,
  `/prices-history?market=<token>&interval=1d&fidelity=60`. All public.
- Execution cost is the spread, not a fee; price buys at best ask.

### ESPN (schedule, results — free, no key)

- `https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard`
  with `groups=80` (FBS), `week=N`, `seasontype=2`, `dates=2026`, `limit=400`.
- Gives kickoff (UTC), venue, `indoor`, `neutralSite`, team abbreviations, scores,
  `status.type.completed`. Name reads "Away at Home".
- ESPN week numbering is canonical for this repo.

### CollegeFootballData (features — static)

- Needs `CFBD_API_KEY` (free at collegefootballdata.com/key). Lines from 2013+, game
  and season advanced stats (PPA, success rate, explosiveness), drives, tempo, weather,
  venues. Python client: `cfbd` on PyPI.
- Never let CFBD work delay price capture.

## Prediction cutoff

All features must be as-of **T-60min** before kickoff. Exchange midpoints are already
near vig-free — do not apply sportsbook de-vig. Sportsbook totals do need de-vig on the
juice, not on the line.

## Stack

- Python 3.11+, uv, ruff (pre-commit), pytest
- httpx for APIs, polars for tables, parquet under `data/` (gitignored)

## Current milestone

v0.1 — secure the data (harvest retained Kalshi ladders, daily capture, Polymarket,
ESPN schedule/results, join table)

## Local rules

- Conventional Commits (feat:, fix:, docs:, refactor:, chore:, test:)
- No `Co-Authored-By` in commits — sole author is Daniel
- Use `uv` not pip; `uv add <pkg>` to add deps
- Pre-commit hooks (ruff) run on every commit
- README/docs in English; conversation can be Spanish
- Tests run offline against fixtures in `tests/fixtures/`; no live API calls in CI
- Never train on a feature that would not have existed at T-60min
- Secrets live in the shell environment (`CFBD_API_KEY`), never in the repo or chat

## How to run

```bash
uv sync
uv run cfb --help
uv run pytest
```

## Where things live

- Source: `src/cfb_canes_analytics/`
- Tests: `tests/`
- Experiments: `docs/experiments/`
- Roadmap: `ROADMAP.md`
- Data (local only): `data/raw/`, `data/processed/`
