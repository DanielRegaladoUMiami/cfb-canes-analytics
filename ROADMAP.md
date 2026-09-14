# Roadmap — CFB Canes Analytics

## Current milestone: v0.1 — secure the data

Exchange prices are the only time-critical asset. Kalshi's rolling retention means
anything not harvested is gone.

- [ ] Kalshi client ported from mlb-canes-analytics (rate-limit aware, ladders, candles)
- [ ] Harvest: every retained settled `KXNCAAFTOTAL` market → ladder + candlesticks
- [ ] Snapshot: open ladders for the coming week, runnable any time (cron-friendly)
- [ ] Polymarket client: per-game O/U markets + CLOB book/history
- [ ] ESPN schedule + results by week (kickoff, venue, indoor, neutral, scores)
- [ ] Game join table: ESPN game id ↔ Kalshi event ↔ Polymarket slug (alias table)
- [ ] Parquet schema + integrity checks (ladder monotone, both venues, settlement = score)

## v0.2 — market baseline

- [ ] Implied distribution from the ladder (monotone fit, interpolate median/mean total)
- [ ] Ladder calibration: is P(total > k) at T-60 honest across k?
- [ ] Cross-venue gaps: Kalshi vs Polymarket vs sportsbook total on the same game
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
