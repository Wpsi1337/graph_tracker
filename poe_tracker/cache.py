from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .data import CurrencyEntry, CurrencySnapshot

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_FILE = CACHE_DIR / "snapshots.json"
DEFAULT_CACHE_TTL = 3600.0  # one hour


def _serialize_entry(entry: CurrencyEntry) -> dict:
    return {
        "name": entry.name,
        "chaos_value": entry.chaos_value,
        "divine_value": entry.divine_value,
        "exalt_value": entry.exalt_value,
        "change_percent": entry.change_percent,
        "sparkline": list(entry.sparkline),
        "trade_count": entry.trade_count,
        "details_id": entry.details_id,
        "icon_url": entry.icon_url,
    }


def _deserialize_entry(data: dict) -> CurrencyEntry:
    return CurrencyEntry(
        name=str(data.get("name", "")),
        chaos_value=float(data.get("chaos_value", 0.0)),
        divine_value=data.get("divine_value"),
        exalt_value=data.get("exalt_value"),
        change_percent=data.get("change_percent"),
        sparkline=data.get("sparkline") or [],
        trade_count=data.get("trade_count"),
        details_id=data.get("details_id"),
        icon_url=data.get("icon_url"),
    )


def _serialize_snapshot(snapshot: CurrencySnapshot) -> dict:
    return {
        "league": snapshot.league,
        "entries": [_serialize_entry(entry) for entry in snapshot.entries],
        "fetched_at": snapshot.fetched_at,
        "source_type": snapshot.source_type,
    }


def _deserialize_snapshot(data: dict) -> Optional[CurrencySnapshot]:
    try:
        entries: List[CurrencyEntry] = []
        raw_entries = data.get("entries", [])
        if isinstance(raw_entries, list):
            for entry_data in raw_entries:
                if isinstance(entry_data, dict):
                    entries.append(_deserialize_entry(entry_data))
        league = str(data.get("league", ""))
        fetched_at = float(data.get("fetched_at", time.time()))
        source_type = str(data.get("source_type", ""))
        return CurrencySnapshot(
            league=league,
            entries=entries,
            fetched_at=fetched_at,
            source_type=source_type,
        )
    except Exception:
        return None


class SnapshotCache:
    """Persisted cache of currency snapshots keyed by normalized category."""

    def __init__(self, ttl: float = DEFAULT_CACHE_TTL) -> None:
        self.ttl = max(ttl, 0.0)
        self._entries: Dict[str, Tuple[CurrencySnapshot, float]] = {}
        self._load()

    @staticmethod
    def _normalize_key(key: str) -> str:
        return key.strip().lower()

    def _load(self) -> None:
        if not CACHE_FILE.exists():
            return
        try:
            with CACHE_FILE.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        now = time.time()
        for key, value in payload.items():
            if not isinstance(value, dict):
                continue
            normalized_key = self._normalize_key(key)
            cached_at = float(value.get("cached_at", 0.0))
            snapshot_data = value.get("snapshot")
            if not isinstance(snapshot_data, dict):
                continue
            snapshot = _deserialize_snapshot(snapshot_data)
            if snapshot is None:
                continue
            if self.ttl and (now - cached_at) >= self.ttl:
                continue
            self._entries[normalized_key] = (snapshot, cached_at)

    def _save(self) -> None:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        payload: Dict[str, dict] = {}
        for key, (snapshot, cached_at) in self._entries.items():
            payload[key] = {
                "cached_at": cached_at,
                "snapshot": _serialize_snapshot(snapshot),
            }
        try:
            with CACHE_FILE.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle)
        except OSError:
            return

    def get(self, key: str) -> Optional[CurrencySnapshot]:
        normalized = self._normalize_key(key)
        entry = self._entries.get(normalized)
        if not entry:
            return None
        snapshot, cached_at = entry
        if self.ttl and (time.time() - cached_at) >= self.ttl:
            self.remove(normalized)
            return None
        return snapshot

    def set(self, key: str, snapshot: CurrencySnapshot) -> None:
        normalized = self._normalize_key(key)
        self._entries[normalized] = (snapshot, time.time())
        self._save()

    def items(self) -> Iterator[tuple[str, CurrencySnapshot]]:
        for key in list(self._entries.keys()):
            snapshot = self.get(key)
            if snapshot is not None:
                yield key, snapshot

    def remove(self, key: str) -> None:
        normalized = self._normalize_key(key)
        if normalized in self._entries:
            self._entries.pop(normalized, None)
            self._save()
