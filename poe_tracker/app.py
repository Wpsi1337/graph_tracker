from __future__ import annotations

import argparse
import locale
import os
import sys
from typing import Iterable, Optional

import curses

from .ui import TrackerConfig, TrackerUI


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="poe-currency-tracker",
        description="Terminal UI for tracking Path of Exile currency values via PoE Ninja.",
    )
    parser.add_argument(
        "--league",
        default="Rise of the Abyssal",
        help="League to track (default: %(default)s)",
    )
    parser.add_argument(
        "--category",
        default="Currency",
        help="Currency overview category (Currency, Fragment, etc.) (default: %(default)s)",
    )
    parser.add_argument(
        "--game",
        choices=["poe", "poe2"],
        default="poe2",
        help="Game context for PoE Ninja API (poe or poe2) (default: %(default)s)",
    )
    parser.add_argument(
        "--ninja-cookie",
        default=os.getenv("POE_NINJA_COOKIE"),
        help="Optional PoE.Ninja session cookie for authenticated requests (env: POE_NINJA_COOKIE)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of currencies to display (default: %(default)s)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=3600.0,
        help="Refresh interval in seconds (default: %(default)s)",
    )
    return parser


def parse_args(argv: Optional[Iterable[str]] = None) -> TrackerConfig:
    parser = build_argument_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.limit <= 0:
        parser.error("--limit must be greater than zero")
    if args.interval < 60:
        parser.error("--interval must be at least 60 seconds to respect API rate limits")
    return TrackerConfig(
        league=args.league,
        category=args.category,
        game=args.game,
        limit=args.limit,
        refresh_interval=args.interval,
        poe_ninja_cookie=args.ninja_cookie,
    )


def run_curses_app(config: TrackerConfig) -> None:
    tracker = TrackerUI(config)
    curses.wrapper(tracker.run)


def main(argv: Optional[Iterable[str]] = None) -> int:
    locale.setlocale(locale.LC_ALL, "")
    try:
        config = parse_args(argv)
        run_curses_app(config)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
