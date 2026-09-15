# Roadmap — CFB Canes Analytics

## Current milestone: v0.1 — secure the data

Exchange prices are the only time-critical asset. Kalshi's rolling retention means
anything not harvested is gone.

- [x] Kalshi client ported from mlb-canes-analytics (rate-limit aware, ladders, candles)
- [x] Harvest: ladders for all 301 retained games (candlestick harvest still running)
- [x] Snapshot: open ladders for the coming week, runnable any time (cron-friendly)
- [x] Polymarket client: per-game O/U markets + CLOB book/history
- [x] ESPN schedule + results by week (kickoff, venue, indoor, neutral, scores)
- [x] Game join table: ESPN game id ↔ Kalshi event ↔ Polymarket event (300/301 matched)
- [x] Parquet schema + integrity checks (`cfb check`: settlement, monotonicity, coverage)
- [ ] Schedule the daily snapshot (cron / launchd) so no day is missed

## v0.2 — market baseline

- [x] Implied distribution from the ladder (monotone fit, interpolate median/mean total)
- [x] Cross-venue gaps: Kalshi vs Polymarket on the same line — none found, see
      `docs/experiments/2026-09-14-market-data-baseline.md`
- [ ] Ladder calibration: is P(total > k) at T-60 honest across k?
- [ ] Metrics: CRPS of the implied distribution, log loss per strike

## v0.3 — features (as-of correct, via CFBD)

- [ ] Offense/defense PPA, success rate, explosiveness — opponent-adjusted, prior games only
- [ ] Tempo: plays per game, seconds per play, pass rate
- [ ] Context: dome, altitude, weather (wind, temp, precip), rest days, week, kickoff slot
- [ ] Market total as a feature (the model corrects the market, it does not replace it)
- [ ] Leakage audit: every feature's source timestamp < kickoff − 60min

## v0.4 — model

- [ ] Baseline: market implied distribution alone
- [ ] Distributional regression on total points (mean + spread), then P(total > k)
- [ ] LightGBM quantile / ridge blend, weights learned on validation
- [ ] Backtest on CFBD lines 2015–2025 (sportsbook benchmark) and Kalshi ladders (2026)

## v0.5 — evaluation and paper trading

- [ ] Walk-forward by week
- [ ] CLV against Kalshi and Polymarket closes
- [ ] ROI net of Kalshi quadratic fees and Polymarket spread
- [ ] Fractional Kelly sizing; paper-trading log for the rest of 2026

## Next up

- Decide whether to add spreads (`KXNCAAFSPREAD`) once totals are proven

## Done

- Repo created 2026-09-14
- Data landscape verified (Kalshi ladders, Polymarket O/U, ESPN, CFBD) — see CLAUDE.md
- Settlement verified: 5,407 strike settlements agree with ESPN box scores, 0 disagree
- Two data traps documented and handled: Kalshi placeholder quotes (0.08/0.92 on untraded
  games) and Polymarket non-game-total O/U markets
