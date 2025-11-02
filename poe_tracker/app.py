from __future__ import annotations

import argparse
import locale
import os
import sys
from typing import Iterable, Optional

import curses

from .ui import TrackerConfig, TrackerUI
from .settings import load_settings, save_settings


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="poe-currency-tracker",
        description="Terminal UI for tracking Path of Exile currency values via PoE Ninja.",
    )
    parser.add_argument(
        "--league",
        default=None,
        help="League to track (default: value saved in tracker_config.json)",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Currency overview category (Currency, Fragment, etc.) (default: value saved in tracker_config.json)",
    )
    parser.add_argument(
        "--game",
        choices=["poe", "poe2"],
        default=None,
        help="Game context for PoE Ninja API (poe or poe2) (default: value saved in tracker_config.json)",
    )
    parser.add_argument(
        "--ninja-cookie",
        default=os.getenv("POE_NINJA_COOKIE"),
        help="Optional PoE.Ninja session cookie for authenticated requests (env: POE_NINJA_COOKIE)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Number of currencies to display (default: value saved in tracker_config.json)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Refresh interval in seconds (default: value saved in tracker_config.json)",
    )
    return parser


def parse_args(argv: Optional[Iterable[str]] = None) -> TrackerConfig:
    settings = load_settings()
    parser = build_argument_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.game:
        settings["game"] = args.game
    if args.league:
        settings["league"] = args.league
    if args.category:
        settings["category"] = args.category
    if args.limit is not None:
        if args.limit <= 0:
            parser.error("--limit must be greater than zero")
        settings["limit"] = args.limit
    if args.interval is not None:
        if args.interval < 60:
            parser.error("--interval must be at least 60 seconds to respect API rate limits")
        settings["interval"] = args.interval
    save_settings(settings)
    game = settings["game"]
    league = settings["league"]
    limit = int(settings["limit"])
    interval = float(settings["interval"])
    category = settings.get("category", "Currency")
    price_mode = settings.get("price_mode", "stash")
    return TrackerConfig(
        league=league,
        category=category,
        game=game,
        limit=limit,
        refresh_interval=interval,
        poe_ninja_cookie=args.ninja_cookie,
        price_mode=price_mode,
        settings=settings,
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
