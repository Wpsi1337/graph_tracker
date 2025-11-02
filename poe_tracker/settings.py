from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

CONFIG_FILE = Path(__file__).resolve().parent.parent / "tracker_config.json"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "game": "poe2",
    "league": "Rise of the Abyssal",
    "interval": 3600.0,
    "limit": 50,
    "category": "Currency",
    "price_mode": "stash",
}


def _prompt_initial_settings() -> Dict[str, Any]:
    print("Path of Exile Currency Tracker - Initial Setup")
    print("Select game:")
    print(" 1: PoE (original client)")
    print(" 2: PoE2")

    game: Optional[str] = None
    while game is None:
        choice = input("Enter choice (1 or 2): ").strip()
        if choice == "1":
            game = "poe"
        elif choice == "2":
            game = "poe2"
        else:
            print("Please enter 1 for PoE or 2 for PoE2.")

    league = ""
    while not league:
        league = input("Enter target league: ").strip()
        if not league:
            print("League cannot be blank.")

    settings = {
        "game": game,
        "league": league,
        "interval": DEFAULT_SETTINGS["interval"],
        "limit": DEFAULT_SETTINGS["limit"],
        "category": DEFAULT_SETTINGS["category"],
        "price_mode": DEFAULT_SETTINGS["price_mode"],
    }
    print(f"Configuration saved to {CONFIG_FILE}.")
    return settings


def _validate_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings)
    game = str(merged.get("game", "poe2")).strip().lower()
    if game not in {"poe", "poe2"}:
        game = "poe2"
    merged["game"] = game

    league = str(merged.get("league", DEFAULT_SETTINGS["league"])).strip()
    merged["league"] = league or DEFAULT_SETTINGS["league"]

    try:
        interval = float(merged.get("interval", DEFAULT_SETTINGS["interval"]))
    except (TypeError, ValueError):
        interval = DEFAULT_SETTINGS["interval"]
    merged["interval"] = max(60.0, interval)

    try:
        limit = int(merged.get("limit", DEFAULT_SETTINGS["limit"]))
    except (TypeError, ValueError):
        limit = DEFAULT_SETTINGS["limit"]
    merged["limit"] = max(1, limit)

    category = str(merged.get("category", DEFAULT_SETTINGS["category"])).strip()
    merged["category"] = category or DEFAULT_SETTINGS["category"]

    price_mode = str(merged.get("price_mode", DEFAULT_SETTINGS["price_mode"])).strip().lower()
    if price_mode not in {"stash", "exchange"}:
        price_mode = DEFAULT_SETTINGS["price_mode"]
    merged["price_mode"] = price_mode
    return merged


def load_settings() -> Dict[str, Any]:
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return _validate_settings(data)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Warning: Failed to load settings ({exc}). Recreating configuration.", file=sys.stderr)

    settings = _prompt_initial_settings()
    save_settings(settings)
    return settings


def save_settings(settings: Dict[str, Any]) -> None:
    sanitized = _validate_settings(settings)
    try:
        with CONFIG_FILE.open("w", encoding="utf-8") as handle:
            json.dump(sanitized, handle, indent=2)
    except OSError as exc:
        print(f"Warning: Failed to write settings ({exc}).", file=sys.stderr)
