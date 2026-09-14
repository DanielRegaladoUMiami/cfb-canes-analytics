# CFB Canes Analytics

> Totals (over/under) model for FBS college football, priced against real exchange
> strike ladders.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

The goal is not to guess whether a game goes over or under. It is to estimate a
**distribution of total points** that is better calibrated than the one already embedded
in market prices, and to prove it out-of-sample with closing-line value (CLV) before any
real money is risked.

## Why exchanges, not just a sportsbook

A sportsbook posts one total (say 54.5) at -110 both ways. Two exchanges post a whole
**ladder** of strikes per game, each with a real bid and ask:

| Venue | Market | Strikes per game | Quotes | Auth |
| --- | --- | --- | --- | --- |
| Kalshi | `KXNCAAFTOTAL` | ~19 (33.5 … 79.5) | bid/ask, minute candlesticks | none for reads |
| Polymarket | `cfb-<away>-<home>-<date>` O/U markets | 2-5 | bid/ask, CLOB book, price history | none for reads |

Read across the ladder and you get the market's implied survival function
P(total > k) for every k, not a single number. That is the benchmark this model has to
beat, and it is nearly vig-free because both venues are exchanges.

Sportsbook closing totals (via CollegeFootballData, DraftKings on ESPN) are kept as the
traditional benchmark. Hard Rock Bet is an execution venue only; it has no public API.

## The constraint that shapes the project

Kalshi's public API keeps settled markets for a **rolling window** only. Verified
2026-09-14: 5,437 settled totals markets across 301 games are retained, the oldest from
2026-08-27 (season week 1), so nothing from 2026 has been lost yet; events from the
2025 season still exist but carry zero markets. There is no backfill. So exchange price
history is **forward-only**: harvest what is retained now, then capture continuously.

CollegeFootballData is static and can be fetched any time; it never gets to delay price
capture.

## Data sources

- **Kalshi** `trade-api/v2` — totals, spread and moneyline series for NCAA football.
- **Polymarket** Gamma + CLOB APIs — per-game O/U, spread, moneyline.
- **ESPN** public scoreboard — schedule, kickoff, venue, indoor/neutral flags, final
  scores (also Kalshi's settlement source).
- **CollegeFootballData** — historical lines (2013+), PPA/EPA, drives, tempo, weather.
  Requires a free `CFBD_API_KEY`.

## How to run

```bash
uv sync
uv run cfb --help
```

## Status

v0.1 — securing the data. See `ROADMAP.md`.

## License

Apache 2.0
