from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import re
from typing import Dict, Iterable, List, Optional, Tuple

from .data import CurrencyEntry, CurrencySnapshot


POE_API_BASE_URL = "https://poe.ninja/api/data"
POE2_API_BASE_URL = "https://poe.ninja/poe2/api/economy"
POE2_TEMP_OVERVIEW_URL = "https://poe.ninja/poe2/api/economy/temp/overview"
POE2_EXCHANGE_OVERVIEW_ENDPOINTS = [
    ("https://poe.ninja/poe2/api/economy/exchange/current/overview", "league", "type"),
    ("https://poe.ninja/poe2/api/economy/currencyexchange/overview", "leagueName", "overviewName"),
]
POE2_EXCHANGE_DETAILS_ENDPOINTS = [
    ("https://poe.ninja/poe2/api/economy/exchange/current/details", "league", "type"),
    ("https://poe.ninja/poe2/api/economy/currencyexchange/details", "leagueName", "overviewName"),
]
USER_AGENT = "poe-currency-tracker/0.1 (+https://github.com/)"
DEFAULT_TIMEOUT = 10
MAX_DETAIL_ENTRIES = 50

_PUNCT_CLEANER = re.compile(r"[^\w\s-]+")

POE_CURRENCY_OVERVIEW_TYPES: List[str] = [
    "Currency",
    "Fragment",
]

POE_ITEM_OVERVIEW_TYPES: List[str] = [
    "AllflameEmber",
    "BaseType",
    "Beast",
    "BlightedMap",
    "BlightRavagedMap",
    "ClusterJewel",
    "Coffin",
    "DeliriumOrb",
    "DivinationCard",
    "Essence",
    "Fossil",
    "HelmetEnchant",
    "Incubator",
    "Invitation",
    "Map",
    "Memory",
    "Oil",
    "Omen",
    "Resonator",
    "Scarab",
    "SkillGem",
    "Tattoo",
    "UniqueAccessory",
    "UniqueArmour",
    "UniqueFlask",
    "UniqueJewel",
    "UniqueMap",
    "UniqueRelic",
    "UniqueWeapon",
    "Vial",
]

_POE_CURRENCY_TYPE_KEYS = {entry.strip().lower() for entry in POE_CURRENCY_OVERVIEW_TYPES}
_POE_ITEM_TYPE_KEYS = {entry.strip().lower() for entry in POE_ITEM_OVERVIEW_TYPES}

def _is_poe_currency_category(category: str) -> bool:
    return category.strip().lower() in _POE_CURRENCY_TYPE_KEYS


def _is_poe_item_category(category: str) -> bool:
    return category.strip().lower() in _POE_ITEM_TYPE_KEYS


POE2_OVERVIEW_ALIASES: Dict[str, List[str]] = {
    "currency": ["Currency", "currency"],
    "fragments": ["Fragments", "fragments", "fragment"],
    "essences": ["Essences", "Essence", "essence"],
    "talismans": ["Talismans", "Talisman", "talismans"],
    "delirium": ["Delirium", "delirium", "delirious"],
    "abyss": ["Abyss", "abyss"],
    "omens": ["Ritual", "Omen", "omen"],
    "catalysts": ["Breach", "Catalyst", "catalysts"],
    "soul-cores": ["Ultimatum", "SoulCores", "SoulCore"],
    "runes": ["Runes", "rune"],
    "expeditions": ["Expedition", "expeditions"],
    "uncutgems": ["UncutGems", "UncutGem", "uncutgems"],
}

POE2_FALLBACK_OVERVIEWS: List[str] = [
    "Currency",
    "Fragments",
    "Essence",
    "Talismans",
    "Delirium",
    "Abyss",
    "Ritual",
    "Catalyst",
    "Ultimatum",
    "Runes",
    "Expedition",
    "UncutGems",
]


class ApiError(RuntimeError):
    """Raised when the PoE Ninja API request fails."""


def _make_request(
    url: str,
    timeout: int,
    headers: Optional[Dict[str, str]] = None,
    ninja_cookie: Optional[str] = None,
) -> bytes:
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if headers:
        request_headers.update(headers)
    cookie_header = _format_cookie(ninja_cookie)
    if cookie_header:
        request_headers.setdefault("Cookie", cookie_header)
    request = urllib.request.Request(
        url,
        headers=request_headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.URLError as exc:
        raise ApiError(str(exc)) from exc


def _extract_float(value: object) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _norm_key(text: Optional[str]) -> Optional[str]:
    if not isinstance(text, str):
        return None
    return text.strip().lower()


def _slug_key(text: Optional[str]) -> Optional[str]:
    base = _norm_key(text)
    if base is None:
        return None
    return base.replace(" ", "-")


def _nopunct_key(text: Optional[str]) -> Optional[str]:
    base = _norm_key(text)
    if base is None:
        return None
    cleaned = _PUNCT_CLEANER.sub("", base)
    return " ".join(cleaned.split())


def _collect_keys(*values: object) -> List[str]:
    keys: List[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (int, float)):
            keys.append(str(int(value)))
            continue
        if not isinstance(value, str):
            continue
        variants = {_norm_key(value), _slug_key(value), _nopunct_key(value)}
        for variant in variants:
            if variant:
                keys.append(variant)
    return keys


def _format_cookie(cookie: Optional[str]) -> Optional[str]:
    if cookie is None:
        return None
    trimmed = cookie.strip()
    if not trimmed:
        return None
    if "=" in trimmed:
        return trimmed
    return f"ninja={trimmed}"


def _humanize_slug(slug: str) -> str:
    text = slug.replace("_", " ").replace("-", " ").strip()
    if not text:
        return slug
    words = [word.capitalize() if word else "" for word in text.split()]
    return " ".join(words)


def _compute_chaos_from_line(line: dict, divine_rate: Optional[float]) -> Optional[float]:
    direct = (
        _extract_float(line.get("chaosEquivalent"))
        or _extract_float(line.get("chaosValue"))
        or _extract_float(line.get("secondaryValue"))
        or _extract_float(line.get("valueChaos"))
        or _extract_float(line.get("secondary"))
    )
    if direct is not None:
        return direct
    primary_value = _extract_float(line.get("primaryValue"))
    if primary_value is not None and divine_rate:
        return primary_value * divine_rate
    volume_primary = _extract_float(line.get("volumePrimaryValue"))
    if volume_primary is not None and divine_rate:
        return volume_primary * divine_rate
    rate = line.get("rate")
    if isinstance(rate, dict):
        chaos_per_item = _extract_float(rate.get("chaosPerItem"))
        if chaos_per_item is not None:
            return chaos_per_item
        items_per_chaos = _extract_float(rate.get("chaos"))
        if items_per_chaos and items_per_chaos > 0:
            return 1.0 / items_per_chaos
        chaos_eq = _extract_float(rate.get("chaosValue"))
        if chaos_eq is not None:
            return chaos_eq
        divine_value = _extract_float(rate.get("divine"))
        if divine_value is not None and divine_rate:
            return divine_value * divine_rate
    return None


def _build_detail_maps(currency_details: Iterable[dict]) -> Tuple[Dict[str, str], Dict[str, str]]:
    icon_lookup: Dict[str, str] = {}
    name_lookup: Dict[str, str] = {}
    for entry in currency_details:
        name = entry.get("name") or entry.get("currencyTypeName") or entry.get("displayName")
        icon = entry.get("icon")
        details_id = entry.get("detailsId")
        identifier = entry.get("id") or entry.get("currencyId")
        alt_details = entry.get("details")
        if isinstance(alt_details, dict):
            name = alt_details.get("name") or name
            icon = alt_details.get("icon") or icon
            if not details_id:
                details_id = alt_details.get("detailsId")
            if not identifier:
                identifier = alt_details.get("id") or alt_details.get("currencyId")
        keys: List[str] = []
        if isinstance(name, str):
            keys.append(name)
        if isinstance(details_id, str):
            keys.append(details_id)
        if isinstance(identifier, (int, float, str)):
            keys.append(str(identifier))
        for key in keys:
            if isinstance(icon, str):
                icon_lookup[key] = icon
            if isinstance(name, str):
                name_lookup[key] = name
    return icon_lookup, name_lookup


def _normalize_icon_url(icon: Optional[str]) -> Optional[str]:
    if not isinstance(icon, str) or not icon.strip():
        return None
    if icon.startswith("http://") or icon.startswith("https://"):
        return icon
    return urllib.parse.urljoin("https://poe.ninja", icon)


def _prepare_exchange_rows(
    exchange_data: Optional[dict],
) -> Tuple[List[dict], Dict[str, str], Dict[str, str], Optional[float]]:
    if not isinstance(exchange_data, dict):
        return [], {}, {}, None
    items_node = exchange_data.get("items")
    lines = exchange_data.get("lines")
    if not isinstance(items_node, list) or not isinstance(lines, list):
        return [], {}, {}, None

    item_lookup: Dict[str, dict] = {}
    icon_lookup: Dict[str, str] = {}
    name_lookup: Dict[str, str] = {}

    for item in items_node:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        if isinstance(raw_id, (int, float)):
            item_id = str(raw_id)
        elif isinstance(raw_id, str):
            item_id = raw_id
        else:
            continue
        details_id = item.get("detailsId") or item_id
        name = item.get("name") or _humanize_slug(details_id if isinstance(details_id, str) else item_id)
        icon_url = _normalize_icon_url(item.get("image"))
        entry = {
            "id": item_id,
            "name": name,
            "detailsId": details_id if isinstance(details_id, str) else None,
            "icon": icon_url,
        }
        item_lookup[item_id] = entry
        if icon_url:
            icon_lookup[item_id] = icon_url
            icon_lookup[name] = icon_url
        name_lookup[item_id] = name
        if isinstance(details_id, str):
            if icon_url:
                icon_lookup[details_id] = icon_url
            name_lookup[details_id] = name

    core = exchange_data.get("core") or {}
    chaos_per_primary = _derive_chaos_per_primary(core)
    divine_rate_from_core = _derive_divine_rate_from_core(core, chaos_per_primary)

    rows: List[dict] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        raw_line_id = line.get("id")
        if isinstance(raw_line_id, (int, float)):
            line_id = str(raw_line_id)
        elif isinstance(raw_line_id, str):
            line_id = raw_line_id
        else:
            continue
        item_info = item_lookup.get(line_id)
        if not item_info:
            continue

        if isinstance(line, dict):
            if "detailsId" not in line and item_info.get("detailsId"):
                line["detailsId"] = item_info.get("detailsId")
            if "name" not in line and item_info.get("name"):
                line["name"] = item_info.get("name")
            if "currencyTypeName" not in line and item_info.get("name"):
                line["currencyTypeName"] = item_info.get("name")

        row: dict = {
            "id": line_id,
            "detailsId": item_info.get("detailsId"),
            "name": item_info.get("name"),
            "item": {
                "id": line_id,
                "name": item_info.get("name"),
                "detailsId": item_info.get("detailsId"),
                "icon": item_info.get("icon"),
            },
        }
        for key in (
            "primaryValue",
            "secondaryValue",
            "volumePrimaryValue",
            "volumeSecondaryValue",
            "volume",
            "maxVolumeCurrency",
            "maxVolumeRate",
        ):
            if key in line:
                row[key] = line.get(key)
        sparkline = line.get("sparkline") or line.get("sparkLine")
        if isinstance(sparkline, dict):
            row["sparkLine"] = sparkline
            row["sparkline"] = sparkline

        primary_value = _extract_float(line.get("primaryValue"))
        chaos_value = None
        if chaos_per_primary is not None and primary_value is not None:
            chaos_value = primary_value * chaos_per_primary
        secondary_value = _extract_float(line.get("secondaryValue"))
        if chaos_value is None and secondary_value is not None:
            chaos_value = secondary_value
        if chaos_value is not None:
            row["chaosValue"] = chaos_value
            row["chaosEquivalent"] = chaos_value
            row["valueChaos"] = chaos_value
            row["value"] = {"chaos": chaos_value}
            rate: Dict[str, float] = {"chaosPerItem": chaos_value}
            if primary_value is not None:
                rate["divine"] = primary_value
                rate["chaosValue"] = chaos_value
            row["rate"] = rate

        rows.append(row)

    return rows, icon_lookup, name_lookup, divine_rate_from_core


def fetch_currency_snapshot(
    league: str,
    category: str = "Currency",
    *,
    game: str = "poe2",
    timeout: int = DEFAULT_TIMEOUT,
    ninja_cookie: Optional[str] = None,
    price_mode: str = "stash",
) -> CurrencySnapshot:
    """Fetch and parse the currency overview for the specified league."""
    normalized_game = (game or "poe2").lower()
    normalized_category = (category or "").strip()
    normalized_mode = (price_mode or "stash").strip().lower()
    if normalized_game == "poe2":
        return _fetch_poe2_snapshot(league, normalized_category or "Currency", timeout, ninja_cookie)
    if normalized_game == "poe":
        if normalized_mode == "exchange" and _is_poe_currency_category(normalized_category):
            return _fetch_poe_exchange_snapshot(league, normalized_category, timeout, ninja_cookie)
        if _is_poe_item_category(normalized_category):
            return _fetch_poe_item_snapshot(league, normalized_category, timeout, ninja_cookie)
        return _fetch_poe_snapshot(league, normalized_category or "Currency", timeout, ninja_cookie)
    return _fetch_poe_snapshot(league, normalized_category or "Currency", timeout, ninja_cookie)


def _merge_entry_attributes(target: CurrencyEntry, source: CurrencyEntry) -> None:
    if source.chaos_value > target.chaos_value:
        target.chaos_value = source.chaos_value
    if source.divine_value is not None and (target.divine_value is None or source.divine_value > target.divine_value):
        target.divine_value = source.divine_value
    if (not target.sparkline) and source.sparkline:
        target.sparkline = source.sparkline
    if (not target.trade_count) and source.trade_count:
        target.trade_count = source.trade_count
    if target.change_percent is None and source.change_percent is not None:
        target.change_percent = source.change_percent
    if (not target.icon_url) and source.icon_url:
        target.icon_url = source.icon_url


def _deduplicate_entries(entries: List[CurrencyEntry]) -> List[CurrencyEntry]:
    key_to_entry: Dict[str, CurrencyEntry] = {}
    ordered: List[CurrencyEntry] = []

    for entry in entries:
        keys = _collect_keys(entry.details_id, entry.name)
        primary_key = keys[0] if keys else entry.name.strip().lower()
        owner = None
        for key in keys:
            owner = key_to_entry.get(key)
            if owner:
                break
        if owner is None:
            owner = entry
            ordered.append(owner)
        else:
            _merge_entry_attributes(owner, entry)
        for key in keys or [primary_key]:
            if key:
                key_to_entry.setdefault(key, owner)

    return ordered


def _apply_exalted_values(entries: List[CurrencyEntry]) -> None:
    exalt_price: Optional[float] = None
    candidates: List[float] = []
    for entry in entries:
        name = entry.name.lower()
        details = (entry.details_id or "").lower()
        if "exalted orb" in name and "perfect" not in name and "greater" not in name:
            if entry.chaos_value > 0:
                candidates.append(entry.chaos_value)
        elif details in {"exalted-orb"} and entry.chaos_value > 0:
            candidates.append(entry.chaos_value)
    if not candidates:
        for entry in entries:
            name = entry.name.lower()
            if "exalt" in name and entry.chaos_value > 0:
                candidates.append(entry.chaos_value)
    if candidates:
        exalt_price = min(candidates)
    if not exalt_price or exalt_price <= 0:
        return
    for entry in entries:
        entry.exalt_value = (entry.chaos_value / exalt_price) if entry.chaos_value else None


def _fetch_poe_snapshot(
    league: str,
    category: str,
    timeout: int,
    ninja_cookie: Optional[str] = None,
) -> CurrencySnapshot:
    query = urllib.parse.urlencode({"league": league, "type": category})
    url = f"{POE_API_BASE_URL}/currencyoverview?{query}"
    payload = _make_request(url, timeout, ninja_cookie=ninja_cookie)
    data = json.loads(payload)
    snapshot = _parse_snapshot_payload(data, league, category, "currencyoverview")
    if snapshot is None:
        raise ApiError("PoE currency overview response missing expected data.")
    _apply_exalted_values(snapshot.entries)
    return snapshot


def _fetch_poe_exchange_snapshot(
    league: str,
    category: str,
    timeout: int,
    ninja_cookie: Optional[str] = None,
) -> CurrencySnapshot:
    query = urllib.parse.urlencode({"league": league, "type": category})
    url = f"{POE_API_BASE_URL.replace('/api/data', '/poe1/api/economy')}/exchange/current/overview?{query}"
    payload = _make_request(url, timeout, ninja_cookie=ninja_cookie)
    data = json.loads(payload)
    working = data.get("payload") if isinstance(data, dict) else None
    if isinstance(working, dict) and working:
        exchange_source = working
    elif isinstance(data, dict):
        exchange_source = data
    else:
        exchange_source = {}
    rows, icon_lookup, name_lookup, divine_rate = _prepare_exchange_rows(exchange_source)
    if not rows:
        raise ApiError(f"No exchange data returned for category '{category}' in league '{league}'.")
    entries = _parse_currency_lines(rows, divine_rate, icon_lookup, name_lookup)
    entries = _deduplicate_entries(entries)
    if divine_rate and divine_rate > 0:
        for entry in entries:
            entry.divine_value = entry.chaos_value / divine_rate if entry.chaos_value else None
    entries.sort(key=lambda item: item.chaos_value, reverse=True)
    _apply_exalted_values(entries)
    return CurrencySnapshot(
        league=league,
        entries=entries,
        fetched_at=time.time(),
        source_type=f"{category}:poe-exchange",
    )

def _fetch_poe_item_snapshot(
    league: str,
    category: str,
    timeout: int,
    ninja_cookie: Optional[str] = None,
) -> CurrencySnapshot:
    query = urllib.parse.urlencode({"league": league, "type": category})
    url = f"{POE_API_BASE_URL}/itemoverview?{query}"
    payload = _make_request(url, timeout, ninja_cookie=ninja_cookie)
    data = json.loads(payload)
    snapshot = _parse_snapshot_payload(data, league, category, "itemoverview")
    if snapshot is None:
        raise ApiError("PoE item overview response missing expected data.")
    _apply_exalted_values(snapshot.entries)
    return snapshot


def _fetch_poe2_snapshot(
    league: str,
    category: str,
    timeout: int,
    ninja_cookie: Optional[str],
) -> CurrencySnapshot:
    exchange_data = _fetch_poe2_exchange_overview(category, league, timeout, ninja_cookie)
    exchange_items, exchange_icons, exchange_names, exchange_divine_rate = _prepare_exchange_rows(exchange_data)
    items: List[dict] = list(exchange_items)
    source_type = "poe2-exchange" if items else "poe2-temp"
    if not items:
        items = _fetch_poe2_items_with_aliases(category, league, timeout, ninja_cookie)
    if not items:
        raise ApiError(f"No data returned for category '{category}' in league '{league}'.")
    overview_payload = _fetch_poe2_overview_payload(category, league, timeout, ninja_cookie)
    overview_lines: List[dict] = []
    overview_icons: Dict[str, str] = {}
    overview_names: Dict[str, str] = {}
    if overview_payload:
        lines = (
            overview_payload.get("lines")
            or overview_payload.get("lineItems")
            or overview_payload.get("entries")
            or overview_payload.get("items")
        )
        if isinstance(lines, list):
            overview_lines = lines
        currency_details = (
            overview_payload.get("currencyDetails")
            or overview_payload.get("currencyDetailsMap")
            or overview_payload.get("currencyData")
            or overview_payload.get("details")
        )
        if isinstance(currency_details, dict):
            overview_icons, overview_names = _build_detail_maps(list(currency_details.values()))
        elif isinstance(currency_details, list):
            overview_icons, overview_names = _build_detail_maps(currency_details)

    icon_lookup: Dict[str, str] = {}
    name_lookup: Dict[str, str] = {}
    icon_lookup.update(overview_icons)
    icon_lookup.update(exchange_icons)
    name_lookup.update(overview_names)
    name_lookup.update(exchange_names)

    divine_rate = _find_divine_from_items(items)
    if not divine_rate and overview_lines:
        divine_rate = _find_divine_from_overview(overview_lines)
    if not divine_rate and exchange_divine_rate:
        divine_rate = exchange_divine_rate
    overview_lookup = _build_overview_lookup(overview_lines, icon_lookup, name_lookup)
    entries = _merge_poe2_data(items, overview_lookup, icon_lookup, name_lookup, divine_rate)
    if exchange_data:
        _apply_exchange_overview_data(
            entries,
            exchange_data,
            icon_lookup,
            name_lookup,
            league,
            category,
            timeout,
            ninja_cookie,
        )
    _add_unmatched_overview_entries(entries, overview_lookup, icon_lookup, name_lookup, divine_rate)
    entries = _deduplicate_entries(entries)
    if divine_rate and divine_rate > 0:
        for entry in entries:
            entry.divine_value = entry.chaos_value / divine_rate if entry.chaos_value else None
    entries.sort(key=lambda item: item.chaos_value, reverse=True)
    _apply_exalted_values(entries)
    return CurrencySnapshot(
        league=league,
        entries=entries,
        fetched_at=time.time(),
        source_type=f"{category}:{source_type}",
    )


def _fetch_poe2_items_with_aliases(
    category: str,
    league: str,
    timeout: int,
    ninja_cookie: Optional[str],
) -> List[dict]:
    normalized = (category or "").lower()
    aliases = POE2_OVERVIEW_ALIASES.get(normalized, [category])
    tried: set[str] = set()
    for alias in aliases + POE2_FALLBACK_OVERVIEWS:
        if not alias or alias in tried:
            continue
        tried.add(alias)
        items = _fetch_poe2_items_once(alias, league, timeout, ninja_cookie)
        if items:
            return items
    return []


def _fetch_poe2_items_once(
    overview: str,
    league: str,
    timeout: int,
    ninja_cookie: Optional[str],
) -> List[dict]:
    params = {"leagueName": league, "overviewName": overview}
    query = urllib.parse.urlencode(params)
    url = f"{POE2_TEMP_OVERVIEW_URL}?{query}"
    headers = {
        "Referer": "https://poe.ninja/",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
    }
    try:
        payload = _make_request(url, timeout, headers=headers, ninja_cookie=ninja_cookie)
    except ApiError:
        return []
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    items = data.get("items")
    if isinstance(items, list):
        return items
    lines = data.get("lines")
    if isinstance(lines, list):
        return lines
    entries = data.get("entries")
    if isinstance(entries, list):
        return entries
    return []


def _fetch_poe2_overview_payload(
    category: str,
    league: str,
    timeout: int,
    ninja_cookie: Optional[str],
) -> Optional[dict]:
    params = {"leagueName": league, "overviewName": category}
    query = urllib.parse.urlencode(params)
    url = f"{POE2_API_BASE_URL}/currencyoverview?{query}"
    try:
        payload = _make_request(url, timeout, ninja_cookie=ninja_cookie)
    except ApiError:
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    payload_node = data.get("payload")
    if isinstance(payload_node, dict):
        return payload_node
    if isinstance(data, dict):
        return data
    return None


def _fetch_poe2_exchange_overview(
    category: str,
    league: str,
    timeout: int,
    ninja_cookie: Optional[str],
) -> Optional[dict]:
    for base_url, league_key, category_key in POE2_EXCHANGE_OVERVIEW_ENDPOINTS:
        params = {league_key: league, category_key: category}
        query = urllib.parse.urlencode(params)
        url = f"{base_url}?{query}"
        try:
            payload = _make_request(url, timeout, ninja_cookie=ninja_cookie)
        except ApiError:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or not data:
            continue
        payload_node = data.get("payload")
        if isinstance(payload_node, dict) and payload_node:
            return payload_node
        return data
    return None


def _apply_exchange_overview_data(
    entries: List[CurrencyEntry],
    exchange_data: Optional[dict],
    icon_lookup: Dict[str, str],
    name_lookup: Dict[str, str],
    league: str,
    category: str,
    timeout: int,
    ninja_cookie: Optional[str],
) -> None:
    if not exchange_data:
        return
    lines = exchange_data.get("lines")
    if not isinstance(lines, list):
        return

    core = exchange_data.get("core") or {}
    chaos_per_primary = _derive_chaos_per_primary(core)
    divine_rate_from_core = _derive_divine_rate_from_core(core, chaos_per_primary)
    if divine_rate_from_core:
        for entry in entries:
            if entry.chaos_value:
                entry.divine_value = entry.chaos_value / divine_rate_from_core

    entry_lookup: Dict[str, CurrencyEntry] = {}
    for entry in entries:
        keys = _collect_keys(entry.details_id, entry.name)
        for key in keys:
            entry_lookup.setdefault(key, entry)

    for line in lines:
        line_keys = _collect_keys(line.get("id"), line.get("detailsId"), line.get("name"))
        target_entry = None
        for key in line_keys:
            candidate = entry_lookup.get(key)
            if candidate:
                target_entry = candidate
                break
        if target_entry is None:
            slug = line.get("id") or line.get("detailsId") or ""
            name = line.get("name") or name_lookup.get(slug) or _humanize_slug(slug) or "Unknown"
            icon = icon_lookup.get(slug)
            target_entry = CurrencyEntry(
                name=name,
                chaos_value=0.0,
                divine_value=None,
                change_percent=None,
                sparkline=[],
                trade_count=None,
                details_id=slug if slug else None,
                icon_url=icon,
            )
            entries.append(target_entry)
            for key in line_keys:
                if key:
                    entry_lookup.setdefault(key, target_entry)

        chaos_value = _compute_exchange_chaos_value(line, chaos_per_primary)
        if chaos_value is not None:
            target_entry.chaos_value = chaos_value
            if divine_rate_from_core:
                target_entry.divine_value = chaos_value / divine_rate_from_core if chaos_value else None

        change_percent = (
            _extract_float(line.get("change"))
            or _extract_float(line.get("sparkLine", {}).get("totalChange"))
        )
        if change_percent is not None:
            target_entry.change_percent = change_percent

        sparkline = (
            _extract_sparkline(line.get("sparkLine"))
            or _extract_sparkline(line.get("receiveSparkLine"))
            or _extract_sparkline(line.get("paySparkLine"))
        )
        if sparkline:
            target_entry.sparkline = sparkline

        trade_count = (
            _extract_trade_count(line)
            or _extract_trade_count(line.get("receive"))
            or _extract_trade_count(line.get("pay"))
        )
        if trade_count:
            target_entry.trade_count = trade_count
        else:
            volume = (
                _extract_float(line.get("volume"))
                or _extract_float(line.get("volumePrimaryValue"))
                or _extract_float(line.get("volumeSecondaryValue"))
            )
            if volume:
                target_entry.trade_count = int(round(volume))

        slug = line.get("id") or line.get("detailsId")
        if slug and not target_entry.details_id:
            target_entry.details_id = slug
        if slug and not target_entry.icon_url:
            target_entry.icon_url = icon_lookup.get(slug)

    detail_ids = [
        entry.details_id
        for entry in entries[:MAX_DETAIL_ENTRIES]
        if entry.details_id
    ]
    detail_data = _fetch_poe2_exchange_details(
        league,
        category,
        detail_ids,
        timeout,
        ninja_cookie,
    )
    if detail_data:
        for entry in entries:
            if not entry.details_id:
                continue
            detail = detail_data.get(entry.details_id)
            if detail:
                _update_entry_from_exchange_detail(entry, detail, icon_lookup, name_lookup, divine_rate_from_core)


def _derive_chaos_per_primary(core: dict) -> Optional[float]:
    if not isinstance(core, dict):
        return None
    primary = core.get("primary")
    secondary = core.get("secondary")
    rates = core.get("rates") or {}

    if primary == "chaos":
        return 1.0
    if secondary == "chaos":
        chaos_rate = _extract_float(rates.get("chaos"))
        if chaos_rate:
            return chaos_rate
    chaos_rate = _extract_float(rates.get("secondary"))
    if chaos_rate:
        return chaos_rate
    return None


def _derive_divine_rate_from_core(core: dict, chaos_per_primary: Optional[float]) -> Optional[float]:
    if not isinstance(core, dict):
        return chaos_per_primary
    primary = core.get("primary")
    if primary == "divine":
        if chaos_per_primary:
            return chaos_per_primary
    rates = core.get("rates") or {}
    divine_rate = _extract_float(rates.get("divine"))
    if divine_rate:
        return divine_rate
    return chaos_per_primary


def _compute_exchange_chaos_value(
    line: dict,
    chaos_per_primary: Optional[float],
) -> Optional[float]:
    if not isinstance(line, dict):
        return None
    primary_value = _extract_float(line.get("primaryValue"))
    if primary_value is not None and chaos_per_primary:
        return primary_value * chaos_per_primary
    secondary_value = _extract_float(line.get("secondaryValue"))
    if secondary_value is not None:
        return secondary_value
    chaos_equivalent = (
        _extract_float(line.get("chaosEquivalent"))
        or _extract_float(line.get("chaosValue"))
        or _extract_float(line.get("valueChaos"))
    )
    if chaos_equivalent is not None:
        return chaos_equivalent
    rate = line.get("rate")
    if isinstance(rate, dict):
        chaos_per_item = _extract_float(rate.get("chaosPerItem"))
        if chaos_per_item is not None:
            return chaos_per_item
        items_per_chaos = _extract_float(rate.get("chaos"))
        if items_per_chaos and items_per_chaos > 0:
            return 1.0 / items_per_chaos
    return None


def _fetch_poe2_exchange_details(
    league: str,
    category: str,
    ids: Iterable[str],
    timeout: int,
    ninja_cookie: Optional[str],
) -> Dict[str, dict]:
    details: Dict[str, dict] = {}
    for index, item_id in enumerate(ids):
        if index >= MAX_DETAIL_ENTRIES:
            break
        for base_url, league_key, category_key in POE2_EXCHANGE_DETAILS_ENDPOINTS:
            params = {league_key: league, category_key: category, "id": item_id}
            query = urllib.parse.urlencode(params)
            url = f"{base_url}?{query}"
            try:
                payload = _make_request(url, timeout, ninja_cookie=ninja_cookie)
            except ApiError:
                continue
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or not data:
                continue
            payload_node = data.get("payload")
            if isinstance(payload_node, dict) and payload_node:
                details[item_id] = payload_node
                break
            details[item_id] = data
            break
    return details


def _update_entry_from_exchange_detail(
    entry: CurrencyEntry,
    detail: dict,
    icon_lookup: Dict[str, str],
    name_lookup: Dict[str, str],
    divine_rate: Optional[float],
) -> None:
    if not isinstance(detail, dict):
        return
    detail_line = detail.get("line")
    if isinstance(detail_line, dict):
        chaos_value = _compute_exchange_chaos_value(detail_line, divine_rate)
        if chaos_value is not None:
            entry.chaos_value = chaos_value
        trade_count = (
            _extract_trade_count(detail_line)
            or _extract_trade_count(detail_line.get("receive"))
            or _extract_trade_count(detail_line.get("pay"))
        )
        if trade_count:
            entry.trade_count = trade_count

    change_percent = (
        _extract_float(detail.get("receiveSparkLine", {}).get("totalChange"))
        or _extract_float(detail.get("paySparkLine", {}).get("totalChange"))
        or _extract_float(detail.get("sparkLine", {}).get("totalChange"))
        or _extract_float(detail.get("totalChange"))
    )
    if change_percent is not None:
        entry.change_percent = change_percent

    sparkline = (
        _extract_sparkline(detail.get("sparkLine"))
        or _extract_sparkline(detail.get("receiveSparkLine"))
        or _extract_sparkline(detail.get("paySparkLine"))
        or _extract_history_series(detail.get("history"))
    )
    if sparkline:
        entry.sparkline = sparkline

    if not entry.trade_count:
        volume = (
            _extract_trade_count(detail.get("history"))
            or _extract_float(detail.get("totalVolume"))
            or _extract_float(detail.get("volume"))
        )
        if volume:
            entry.trade_count = int(round(volume))

    detail_icon = detail.get("icon")
    if isinstance(detail_icon, str) and detail_icon and not entry.icon_url:
        entry.icon_url = detail_icon

    name = detail.get("name")
    if isinstance(name, str) and name.strip():
        entry.name = name.strip()

    if entry.details_id and not entry.icon_url:
        entry.icon_url = icon_lookup.get(entry.details_id)
    if entry.details_id and entry.name == "Unknown":
        mapped = name_lookup.get(entry.details_id)
        if mapped:
            entry.name = mapped

    if divine_rate and entry.chaos_value:
        entry.divine_value = entry.chaos_value / divine_rate


def _extract_history_series(history: object) -> List[float]:
    if not isinstance(history, list):
        return []
    values: List[float] = []
    for point in history:
        if isinstance(point, dict):
            value = _extract_float(
                point.get("value")
                or point.get("chaosValue")
                or point.get("secondaryValue")
            )
        else:
            value = _extract_float(point)
        if value is not None:
            values.append(value)
    return values


def _build_overview_lookup(
    lines: Iterable[dict],
    icon_lookup: Dict[str, str],
    name_lookup: Dict[str, str],
) -> Dict[str, dict]:
    lookup: Dict[str, dict] = {}
    for line in lines:
        names = [
            line.get("currencyTypeName"),
            line.get("name"),
            line.get("detailsId"),
            line.get("id"),
        ]
        for key in _collect_keys(*names):
            lookup[key] = line
        currency_id = line.get("currencyId")
        if isinstance(currency_id, (int, float, str)):
            lookup[str(currency_id)] = line
        details_id = line.get("detailsId")
        if isinstance(details_id, str):
            mapped_name = name_lookup.get(details_id)
            if mapped_name:
                for key in _collect_keys(mapped_name):
                    lookup[key] = line
    return lookup


def _merge_poe2_data(
    items: Iterable[dict],
    overview_lookup: Dict[str, dict],
    icon_lookup: Dict[str, str],
    name_lookup: Dict[str, str],
    divine_rate: Optional[float],
) -> List[CurrencyEntry]:
    entries: List[CurrencyEntry] = []

    for row in items:
        item_node = row.get("item")
        if not isinstance(item_node, dict):
            item_node = row.get("currency") if isinstance(row.get("currency"), dict) else {}
        name = _extract_poe2_name(row, item_node, name_lookup)
        chaos_value = _infer_poe2_chaos_value(row, divine_rate)
        details_id = _infer_details_id(row, item_node)
        currency_id = _infer_currency_id(row, item_node)
        icon = None
        if isinstance(item_node, dict):
            icon = item_node.get("icon")
        if icon is None and details_id in icon_lookup:
            icon = icon_lookup.get(details_id)
        if icon is None and name in icon_lookup:
            icon = icon_lookup.get(name)
        entry = CurrencyEntry(
            name=name,
            chaos_value=chaos_value or 0.0,
            divine_value=None,
            change_percent=None,
            sparkline=_extract_sparkline(row.get("sparkLine"))
            or _extract_sparkline(row.get("sparkline")),
            trade_count=_extract_trade_count(row)
            or _extract_trade_count(row.get("listing")),
            details_id=details_id,
            icon_url=icon,
        )
        if divine_rate and divine_rate > 0 and entry.chaos_value:
            entry.divine_value = entry.chaos_value / divine_rate

        keys = set(_collect_keys(name, details_id, currency_id, row.get("detailsId"), row.get("id")))
        entries.append(entry)

        overview_line = None
        for key in keys:
            overview_line = overview_lookup.get(key)
            if overview_line:
                break
        if overview_line:
            _update_entry_from_overview(entry, overview_line, icon_lookup, name_lookup, divine_rate)

    return entries


def _add_unmatched_overview_entries(
    entries: List[CurrencyEntry],
    overview_lookup: Dict[str, dict],
    icon_lookup: Dict[str, str],
    name_lookup: Dict[str, str],
    divine_rate: Optional[float],
) -> None:
    existing_keys = set()
    for entry in entries:
        existing_keys.update(
            _collect_keys(entry.name, entry.details_id)
        )
    for line in overview_lookup.values():
        name_candidates = _collect_keys(
            line.get("currencyTypeName"),
            line.get("name"),
            line.get("detailsId"),
            line.get("id"),
        )
        if any(key in existing_keys for key in name_candidates):
            continue
        entry = CurrencyEntry(
            name=line.get("currencyTypeName") or line.get("name") or "Unknown",
            chaos_value=_compute_chaos_from_line(line, divine_rate),
            divine_value=None,
            change_percent=None,
            sparkline=[],
            trade_count=None,
            details_id=line.get("detailsId"),
            icon_url=None,
        )
        _update_entry_from_overview(entry, line, icon_lookup, name_lookup, divine_rate)
        if divine_rate and divine_rate > 0 and entry.chaos_value:
            entry.divine_value = entry.chaos_value / divine_rate
        entries.append(entry)
        existing_keys.update(_collect_keys(entry.name, entry.details_id))


def _update_entry_from_overview(
    entry: CurrencyEntry,
    overview_line: dict,
    icon_lookup: Dict[str, str],
    name_lookup: Dict[str, str],
    divine_rate: Optional[float],
) -> None:
    chaos_equiv = _compute_chaos_from_line(overview_line, divine_rate)
    if chaos_equiv is not None:
        entry.chaos_value = chaos_equiv
    change_percent = (
        _extract_float(overview_line.get("receiveSparkLine", {}).get("totalChange"))
        or _extract_float(overview_line.get("paySparkLine", {}).get("totalChange"))
        or _extract_float(overview_line.get("sparkLine", {}).get("totalChange"))
    )
    if change_percent is not None:
        entry.change_percent = change_percent
    sparkline = (
        _extract_sparkline(overview_line.get("receiveSparkLine"))
        or _extract_sparkline(overview_line.get("paySparkLine"))
        or _extract_sparkline(overview_line.get("sparkLine"))
    )
    if sparkline:
        entry.sparkline = sparkline
    trade_count = (
        _extract_trade_count(overview_line.get("receive"))
        or _extract_trade_count(overview_line.get("pay"))
        or _extract_trade_count(overview_line)
    )
    if trade_count:
        entry.trade_count = trade_count
    else:
        for key in ("volumePrimaryValue", "volumeSecondaryValue", "volume"):
            volume = overview_line.get(key)
            float_volume = _extract_float(volume)
            if float_volume:
                entry.trade_count = int(round(float_volume))
                break
    details_id = overview_line.get("detailsId")
    if isinstance(details_id, str):
        entry.details_id = entry.details_id or details_id
        if entry.icon_url is None:
            entry.icon_url = icon_lookup.get(details_id)
        mapped_name = name_lookup.get(details_id)
        if mapped_name:
            entry.name = mapped_name
    if entry.icon_url is None and entry.name in icon_lookup:
        entry.icon_url = icon_lookup.get(entry.name)


def _extract_poe2_name(row: dict, item_node: dict, name_lookup: Optional[Dict[str, str]] = None) -> str:
    possible_fields = [
        row.get("name"),
        row.get("currencyTypeName"),
        row.get("displayName"),
        row.get("currencyName"),
        row.get("receiveCurrencyName"),
        row.get("payCurrencyName"),
        item_node.get("name") if isinstance(item_node, dict) else None,
        item_node.get("displayName") if isinstance(item_node, dict) else None,
    ]
    for field in possible_fields:
        if isinstance(field, str) and field.strip():
            return field.strip()
    details_id = row.get("detailsId") or item_node.get("detailsId")
    if isinstance(details_id, str) and name_lookup:
        mapped = name_lookup.get(details_id)
        if mapped:
            return mapped
    slug_source = row.get("id") or details_id
    if isinstance(slug_source, str):
        humanized = _humanize_slug(slug_source)
        if humanized:
            return humanized
    return "Unknown"


def _find_divine_from_items(items: Iterable[dict]) -> Optional[float]:
    for row in items:
        item_node = row.get("item")
        if not isinstance(item_node, dict):
            item_node = {}
        name = (item_node.get("name") or row.get("name") or "").lower()
        if "divine orb" in name:
            for key in ("chaosValue", "chaosEquivalent", "valueChaos"):
                value = _extract_float(row.get(key))
                if value:
                    return value
            rate = row.get("rate")
            if isinstance(rate, dict):
                chaos_per_item = _extract_float(rate.get("chaosPerItem"))
                if chaos_per_item:
                    return chaos_per_item
                items_per_chaos = _extract_float(rate.get("chaos"))
                if items_per_chaos and items_per_chaos > 0:
                    return 1.0 / items_per_chaos
            primary_value = _extract_float(row.get("primaryValue"))
            if primary_value:
                return primary_value
    return None


def _find_divine_from_overview(lines: Iterable[dict]) -> Optional[float]:
    for line in lines:
        name = (line.get("currencyTypeName") or "").lower()
        details_id = line.get("detailsId") or ""
        if "divine" in name or ("divine" in details_id if isinstance(details_id, str) else False):
            value = _extract_float(line.get("chaosEquivalent"))
            if value:
                return value
    return None


def _infer_poe2_chaos_value(row: dict, divine_rate: Optional[float]) -> Optional[float]:
    for key in ("chaosValue", "chaosEquivalent", "valueChaos", "chaos"):
        value = _extract_float(row.get(key))
        if value is not None:
            return value
    rate = row.get("rate")
    if isinstance(rate, dict):
        items_per_chaos = _extract_float(rate.get("chaos"))
        if items_per_chaos and items_per_chaos > 0:
            return 1.0 / items_per_chaos
        chaos_per_item = _extract_float(rate.get("chaosPerItem"))
        if chaos_per_item is not None:
            return chaos_per_item
        chaos_equiv = _extract_float(rate.get("chaosValue"))
        if chaos_equiv is not None:
            return chaos_equiv
        divine_value = _extract_float(rate.get("divine"))
        if divine_value is not None and divine_rate:
            return divine_value * divine_rate
    primary_value = _extract_float(row.get("primaryValue"))
    if primary_value is not None and divine_rate:
        return primary_value * divine_rate
    value_node = row.get("value")
    if isinstance(value_node, dict):
        for key in ("chaos", "chaosValue", "value"):
            value = _extract_float(value_node.get(key))
            if value is not None:
                return value
    fallback = _extract_float(row.get("value"))
    if fallback is not None:
        return fallback
    return None


def _parse_snapshot_payload(
    raw_data: object,
    league: str,
    category: str,
    source: str,
) -> Optional[CurrencySnapshot]:
    if not isinstance(raw_data, dict):
        return None
    data = raw_data.get("payload")
    if isinstance(data, dict):
        working = data
    else:
        working = raw_data

    lines = (
        working.get("lines")
        or working.get("lineItems")
        or working.get("entries")
        or working.get("result")
        or working.get("results")
        or working.get("data")
    )
    if not isinstance(lines, list):
        return None

    currency_details = (
        working.get("currencyDetails")
        or working.get("currencyDetailsMap")
        or working.get("currencyData")
        or working.get("details")
    )
    if isinstance(currency_details, dict):
        details_iterable = list(currency_details.values())
    elif isinstance(currency_details, list):
        details_iterable = currency_details
    else:
        details_iterable = []

    icon_lookup, name_lookup = _build_detail_maps(details_iterable)

    divine_chaos_value = _find_divine_chaos_value(lines)
    entries = _parse_currency_lines(lines, divine_chaos_value, icon_lookup, name_lookup)
    entries.sort(key=lambda item: item.chaos_value, reverse=True)
    return CurrencySnapshot(
        league=league,
        entries=entries,
        fetched_at=time.time(),
        source_type=f"{category}:{source}",
    )


def _find_divine_chaos_value(lines: Iterable[dict]) -> Optional[float]:
    for line in lines:
        name = line.get("currencyTypeName")
        details_id = line.get("detailsId")
        currency_node = _extract_currency_node(line)
        node_name = None
        node_details = None
        if isinstance(currency_node, dict):
            node_name = currency_node.get("name")
            node_details = currency_node.get("detailsId")
        if name == "Divine Orb" or node_name == "Divine Orb":
            return _extract_float(line.get("chaosEquivalent"))
        if isinstance(details_id, str) and "divine" in details_id:
            return _extract_float(line.get("chaosEquivalent"))
        if isinstance(node_details, str) and "divine" in node_details:
            return _extract_float(line.get("chaosEquivalent"))
    return None


def _parse_currency_lines(
    lines: Iterable[dict],
    divine_chaos_value: Optional[float],
    icon_lookup: Dict[str, str],
    name_lookup: Dict[str, str],
) -> List[CurrencyEntry]:
    entries: List[CurrencyEntry] = []
    for line in lines:
        name = _infer_currency_name(line, name_lookup)
        chaos_value = _infer_chaos_value(line)

        change_percent = None
        receive_spark = line.get("receiveSparkLine")
        if isinstance(receive_spark, dict):
            change_percent = _extract_float(receive_spark.get("totalChange"))
        if change_percent is None:
            pay_spark = line.get("paySparkLine")
            if isinstance(pay_spark, dict):
                change_percent = _extract_float(pay_spark.get("totalChange"))
        if change_percent is None:
            generic_spark = line.get("sparkLine") or line.get("sparkline")
            if isinstance(generic_spark, dict):
                change_percent = _extract_float(generic_spark.get("totalChange"))

        sparkline = (
            _extract_sparkline(receive_spark)
            or _extract_sparkline(line.get("paySparkLine"))
            or _extract_sparkline(line.get("sparkLine"))
        )
        trade_count = (
            _extract_trade_count(line.get("receive"))
            or _extract_trade_count(line.get("pay"))
            or _extract_trade_count(line)
        )

        divine_value = None
        if divine_chaos_value and divine_chaos_value > 0:
            divine_value = chaos_value / divine_chaos_value

        currency_node = _extract_currency_node(line)
        details_id = _infer_details_id(line, currency_node)
        currency_id = _infer_currency_id(line, currency_node)
        icon = None
        if isinstance(name, str):
            icon = icon_lookup.get(name)
        if icon is None and isinstance(details_id, str):
            icon = icon_lookup.get(details_id)
        if icon is None and isinstance(currency_id, (int, float, str)):
            icon = icon_lookup.get(str(currency_id))
        if icon is None and isinstance(currency_node, dict):
            icon = currency_node.get("icon")

        entries.append(
            CurrencyEntry(
                name=str(name),
                chaos_value=chaos_value,
                divine_value=divine_value,
                change_percent=change_percent,
                sparkline=sparkline,
                trade_count=trade_count,
                details_id=details_id if isinstance(details_id, str) else None,
                icon_url=icon,
            )
        )
    return entries


def _extract_sparkline(sparkline: object) -> List[float]:
    if isinstance(sparkline, list):
        return [value for value in (_extract_float(item) for item in sparkline) if value is not None]
    if not isinstance(sparkline, dict):
        return []
    data = sparkline.get("data") or sparkline.get("values") or sparkline.get("sparkLine")
    if not isinstance(data, list):
        return []
    result = []
    for item in data:
        float_value = _extract_float(item)
        if float_value is not None:
            result.append(float_value)
    return result


def _extract_trade_count(node: object) -> Optional[int]:
    if not isinstance(node, dict):
        return None
    for key in ("count", "volume", "listingCount", "total"):
        value = node.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def _extract_currency_node(line: dict) -> Optional[dict]:
    candidates = [
        line.get("currency"),
        line.get("payCurrency"),
        line.get("targetCurrency"),
        line.get("receiveCurrency"),
        line.get("item"),
        line.get("currencyDetails"),
        line.get("details"),
    ]
    for node in candidates:
        if isinstance(node, dict):
            return node
    return None


def _infer_currency_id(line: dict, currency_node: Optional[dict]) -> Optional[str]:
    candidate_keys = [
        "currencyId",
        "id",
        "receiveCurrencyId",
        "payCurrencyId",
        "targetCurrencyId",
        "itemId",
        "currencyTypeId",
    ]
    for key in candidate_keys:
        value = line.get(key)
        if isinstance(value, (int, float)):
            return str(int(value))
        if isinstance(value, str) and value:
            return value
    if isinstance(currency_node, dict):
        for key in candidate_keys:
            value = currency_node.get(key)
            if isinstance(value, (int, float)):
                return str(int(value))
            if isinstance(value, str) and value:
                return value
    return None


def _infer_details_id(line: dict, currency_node: Optional[dict]) -> Optional[str]:
    candidate_keys = [
        "detailsId",
        "detailId",
        "currencyDetailsId",
        "payCurrencyDetailsId",
        "receiveCurrencyDetailsId",
    ]
    for key in candidate_keys:
        value = line.get(key)
        if isinstance(value, str):
            return value
    if isinstance(currency_node, dict):
        for key in candidate_keys:
            value = currency_node.get(key)
            if isinstance(value, str):
                return value
    # fall back to numeric id
    inferred_id = _infer_currency_id(line, currency_node)
    return inferred_id


def _infer_currency_name(line: dict, name_lookup: Dict[str, str]) -> str:
    name_fields = [
        "currencyTypeName",
        "name",
        "displayName",
        "itemName",
        "currencyName",
        "receiveCurrencyName",
        "payCurrencyName",
        "receiveCurrencyTypeName",
        "payCurrencyTypeName",
        "typeName",
    ]
    receive_name = line.get("receiveCurrencyName") or line.get("receiveCurrencyTypeName")
    pay_name = line.get("payCurrencyName") or line.get("payCurrencyTypeName")
    if isinstance(receive_name, str) and isinstance(pay_name, str):
        combo = f"{receive_name} for {pay_name}"
        if combo.strip():
            return combo
    for field in name_fields:
        value = line.get(field)
        if isinstance(value, str) and value.strip():
            return value
    currency_node = _extract_currency_node(line)
    if isinstance(currency_node, dict):
        for key in ("name", "displayName", "typeName", "currencyTypeName"):
            value = currency_node.get(key)
            if isinstance(value, str):
                return value
    details_id = line.get("detailsId")
    if isinstance(details_id, str):
        mapped = name_lookup.get(details_id)
        if mapped:
            return mapped
    if isinstance(currency_node, dict):
        details_id = currency_node.get("detailsId")
        if isinstance(details_id, str):
            mapped = name_lookup.get(details_id)
            if mapped:
                return mapped
    currency_id = _infer_currency_id(line, currency_node)
    if isinstance(currency_id, str):
        mapped = name_lookup.get(currency_id)
        if mapped:
            return mapped
    return "Unknown"


def _infer_chaos_value(line: dict) -> float:
    for key in ("chaosEquivalent", "chaosValue", "valueChaos", "value"):
        value = _extract_float(line.get(key))
        if value is not None:
            return value
    receive = line.get("receive") or line.get("receiveListing") or line.get("receiveCurrency")
    if isinstance(receive, dict):
        for key in ("value", "valueChaos", "chaosEquivalent", "chaosValue"):
            value = _extract_float(receive.get(key))
            if value is not None:
                return value
    pay = line.get("pay")
    if isinstance(pay, dict):
        for key in ("value", "valueChaos", "chaosEquivalent", "chaosValue"):
            value = _extract_float(pay.get(key))
            if value is not None:
                return value
    value_node = line.get("value")
    if isinstance(value_node, dict):
        for key in ("chaos", "chaosValue", "value"):
            value = _extract_float(value_node.get(key))
            if value is not None:
                return value
    return 0.0
