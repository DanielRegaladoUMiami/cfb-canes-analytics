"""``cfb`` command line: harvest, snapshot, schedule, ladder, status."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime

import polars as pl

from . import checks as checks_mod
from . import edges as edges_mod
from . import harvest as harvest_mod
from . import snapshot as snapshot_mod
from .espn import EspnClient
from .kalshi import TOTAL_SERIES, EventKey, KalshiClient
from .ladder import implied_mean, implied_quantile, implied_survival, ladder_from_markets
from .polymarket import PolymarketClient
from .storage import data_dir, raw_path, read_or_none


def _parse_weeks(text: str | None) -> list[int] | None:
    if not text or text == "current":
        return None
    weeks: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            weeks.extend(range(int(a), int(b) + 1))
        else:
            weeks.append(int(part))
    return weeks


def cmd_harvest(args: argparse.Namespace) -> int:
    intervals = tuple(int(x) for x in args.intervals.split(",")) if args.intervals else ()
    with KalshiClient() as client:
        out = harvest_mod.harvest_all(client, data_dir(), series=args.series, intervals=intervals)
    print(out)
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    base = data_dir()
    weeks = _parse_weeks(args.weeks)
    with EspnClient() as espn:
        games = snapshot_mod.snapshot_espn(espn, base, year=args.year, weeks=weeks)
    if not args.skip_kalshi:
        with KalshiClient() as kalshi:
            snapshot_mod.snapshot_kalshi(kalshi, base, series=args.series)
    if not args.skip_polymarket:
        with PolymarketClient() as pm:
            snapshot_mod.snapshot_polymarket(pm, base, games)
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    with EspnClient() as espn:
        games = snapshot_mod.snapshot_espn(
            espn, data_dir(), year=args.year, weeks=_parse_weeks(args.weeks)
        )
    print(f"{len(games)} games")
    return 0


def cmd_ladder(args: argparse.Namespace) -> int:
    with KalshiClient() as client:
        event = client.get_event(args.event_ticker)
        markets = client.get_event_markets(args.event_ticker)
    key = EventKey.from_event(event)
    points = ladder_from_markets(markets)
    print(f"{key.title}  [{key.sub_title}]  {len(points)} strikes")
    print(f"{'strike':>7} {'bid':>6} {'ask':>6} {'mid':>6} {'volume':>10}")
    for p in points:
        print(
            f"{p.strike:>7.1f} {p.bid if p.bid is not None else float('nan'):>6.2f} "
            f"{p.ask if p.ask is not None else float('nan'):>6.2f} "
            f"{p.mid if p.mid is not None else float('nan'):>6.3f} {p.volume or 0:>10.0f}"
        )
    surv = implied_survival(points)
    if surv:
        print(
            f"implied median total {implied_quantile(surv, 0.5):.1f}   "
            f"mean {implied_mean(surv):.1f}   "
            f"p25/p75 {implied_quantile(surv, 0.25):.1f}/{implied_quantile(surv, 0.75):.1f}"
        )
    return 0


def cmd_edges(args: argparse.Namespace) -> int:
    rows = edges_mod.build_rows(data_dir(), min_open_interest=args.min_oi)
    if not rows:
        print("no rows — run 'cfb snapshot' first")
        return 1
    hits = edges_mod.disagreements(rows, threshold=args.threshold)
    print(f"{len(rows)} shared lines, {len(hits)} disagree by >= {args.threshold:.0%}")
    print(
        f"{'game':<46} {'line':>6} {'kalshi':>7} {'pm bid/ask':>12} "
        f"{'side':>5} {'edge':>6} {'k.med':>6} {'k.oi':>9}"
    )
    for r in (hits or rows)[: args.limit]:
        bid = f"{r.pm_over_bid:.2f}" if r.pm_over_bid is not None else "  - "
        ask = f"{r.pm_over_ask:.2f}" if r.pm_over_ask is not None else "  - "
        print(
            f"{r.game[:46]:<46} {r.line:>6.1f} {r.kalshi_p_over:>7.3f} "
            f"{bid + '/' + ask:>12} {r.best_side or '-':>5} {r.best_edge:>6.3f} "
            f"{r.kalshi_median:>6.1f} {r.kalshi_oi:>9,.0f}"
        )
    print(
        "\nGross of Kalshi fees. Low open interest means the Kalshi side is "
        "a quote, not a consensus."
    )
    return 0


def cmd_board(args: argparse.Namespace) -> int:
    rows = edges_mod.build_board(data_dir())
    if not rows:
        print("no rows — run 'cfb snapshot' first")
        return 1
    if args.min_oi:
        rows = [r for r in rows if r.open_interest >= args.min_oi]
    print(f"{len(rows)} upcoming games with a quoted Kalshi ladder")
    print(
        f"{'kickoff':<12} {'game':<44} {'median':>7} {'p25-p75':>12} "
        f"{'book':>6} {'diff':>6} {'oi':>9}"
    )
    for r in rows[: args.limit]:
        when = r.kickoff.strftime("%a %H:%MZ") if r.kickoff else "-"
        book = f"{r.book_total:.1f}" if r.book_total is not None else "-"
        diff = f"{r.diff:+.1f}" if r.diff is not None else "-"
        span = f"{r.kalshi_p25:.0f}-{r.kalshi_p75:.0f}"
        print(
            f"{when:<12} {r.game[:44]:<44} {r.kalshi_median:>7.1f} {span:>12} "
            f"{book:>6} {diff:>6} {r.open_interest:>9,.0f}"
        )
    print("\nmedian = total points where Kalshi's ladder says over and under are even.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    results = checks_mod.run_all(data_dir())
    for result in results:
        print(result)
        for example in result.examples:
            print(f"    {example}")
    return 0 if all(r.ok for r in results) else 1


def cmd_status(args: argparse.Namespace) -> int:
    base = data_dir()
    print(f"data dir: {base.resolve()}")
    for name in (
        "kalshi_events.parquet",
        "kalshi_markets.parquet",
        "kalshi_candles_60.parquet",
        "kalshi_candles_1.parquet",
        "kalshi_candles_log.parquet",
        "kalshi_snapshots.parquet",
        "polymarket_snapshots.parquet",
        "espn_games.parquet",
    ):
        df = read_or_none(raw_path(name, base))
        if df is None:
            print(f"  {name:<32} -")
            continue
        extra = ""
        if "captured_at" in df.columns:
            extra = f"  latest capture {df.get_column('captured_at').max()}"
        elif "close_time" in df.columns and df.height:
            closes = df.get_column("close_time").drop_nulls()
            if closes.len():
                extra = f"  close_time {closes.min()} .. {closes.max()}"
        print(f"  {name:<32} {df.height:>9,} rows{extra}")
    events = read_or_none(raw_path("kalshi_events.parquet", base))
    markets = read_or_none(raw_path("kalshi_markets.parquet", base))
    if events is not None and markets is not None:
        with_markets = (
            markets.filter(pl.col("status") != "no_markets").get_column("event_ticker").n_unique()
        )
        print(f"  games with a retained ladder: {with_markets} / {events.height}")
    print(f"now: {datetime.now(UTC).isoformat(timespec='seconds')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cfb", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("harvest", help="harvest retained settled Kalshi ladders + candles")
    p.add_argument("--series", default=TOTAL_SERIES)
    p.add_argument("--intervals", default="60,1", help="candle intervals, e.g. '60,1' or ''")
    p.set_defaults(func=cmd_harvest)

    p = sub.add_parser("snapshot", help="capture open Kalshi/Polymarket ladders + ESPN schedule")
    p.add_argument("--year", type=int, default=datetime.now(UTC).year)
    p.add_argument("--weeks", default="current", help="'current', '4', '3-5' or '3,4'")
    p.add_argument("--series", default=TOTAL_SERIES)
    p.add_argument("--skip-kalshi", action="store_true")
    p.add_argument("--skip-polymarket", action="store_true")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("schedule", help="fetch ESPN schedule/results into parquet")
    p.add_argument("--year", type=int, default=datetime.now(UTC).year)
    p.add_argument("--weeks", default="1-16")
    p.set_defaults(func=cmd_schedule)

    p = sub.add_parser("ladder", help="print a live Kalshi ladder with implied median/mean")
    p.add_argument("event_ticker")
    p.set_defaults(func=cmd_ladder)

    p = sub.add_parser("edges", help="where Kalshi's ladder and Polymarket's price disagree")
    p.add_argument("--threshold", type=float, default=0.05, help="minimum gross edge")
    p.add_argument("--min-oi", type=float, default=0.0, help="minimum Kalshi open interest")
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_edges)

    p = sub.add_parser("board", help="upcoming games: Kalshi implied total vs the book")
    p.add_argument("--min-oi", type=float, default=0.0)
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(func=cmd_board)

    p = sub.add_parser("check", help="integrity checks on the local data")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("status", help="row counts and coverage of local data")
    p.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
