# 2026-09-14 — Can the two exchanges be beaten against each other?

## Hypothesis

Kalshi lists ~19 total-points strikes per college football game; Polymarket lists one to
five. If the two exchanges price the same line differently by more than the cost of
crossing the spread, that gap is takeable without any predictive model.

## Setup

- Kalshi `KXNCAAFTOTAL`, every open event, full strike ladder, captured 2026-09-15 01:23Z.
- Polymarket Gamma tag `cfb` (id 100351), 129 game events, full-game O/U markets only.
- ESPN scoreboard, FBS (group 80) and FCS (group 81), weeks 1-4 of 2026.
- Kalshi's ladder is converted to a survival function S(k) = P(total > k), projected onto
  non-increasing sequences with pool-adjacent-violators, then interpolated to whatever
  line Polymarket offers.

## Result

**No takeable gap.** Across 20 lines quoted on both venues, the largest disagreement was
0.8 cents, and every one of them sat inside the Polymarket bid/ask. Nine of the twenty
had Kalshi *inside* Polymarket's spread on both sides.

| Quantity | Value |
| --- | --- |
| Lines quoted on both venues | 20 |
| Disagreements ≥ 3 cents | 0 |
| Largest disagreement | 0.008 |

The two exchanges agree. Any edge in this market has to come from a model that beats
both, not from shopping between them.

## Two data traps found on the way

**Placeholder quotes.** On a game nobody trades, Kalshi shows `0.08 / 0.92` on every
strike with zero open interest — verified on `KXNCAAFTOTAL-26SEP19UTMMEM`, 16 of 19
strikes. Every midpoint is then 0.50, and a naive read produces an implied distribution
saying that every total from 36 to 78 is equally likely. Strikes wider than a 0.25 spread
are now dropped, and a ladder with fewer than three real quotes returns no distribution
at all.

**Polymarket's `line` field is not always a game total.** Half totals, quarter totals,
team totals and total-touchdowns markets all carry a `line` and Over/Under outcomes.
Comparing them to a Kalshi full-game ladder produced fake 99-cent edges on lines of 2.5
and 3.5. Markets are now classified by question shape, and only `game_total` is compared.

## Settlement is trustworthy

Kalshi settles totals off ESPN, and it does so exactly. Joining 300 retained games to
their ESPN box scores and checking every strike:

| Check | Result |
| --- | --- |
| Strike settlements vs final score | 5,407 agree, 0 disagree |
| Kalshi games matched to ESPN | 300 of 301 (1 ambiguous, a duplicated fixture) |
| Ladders monotone within 10 cents | 73 of 73 quoted |

That means the join is sound and the label for a future model — did the total go over
strike k — can be taken straight from ESPN.

## Decision

Stop looking for cross-venue arbitrage; it is not there. Next: characterise how well the
Kalshi closing ladder itself is calibrated on the 300 settled games, which sets the bar
any model has to clear. That needs the candlestick harvest to finish.
