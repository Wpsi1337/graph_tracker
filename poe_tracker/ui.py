from __future__ import annotations

import curses
import re
import time
from dataclasses import dataclass
from typing import List, Optional

from .api import (
    ApiError,
    fetch_currency_snapshot,
    POE2_FALLBACK_OVERVIEWS,
    POE2_OVERVIEW_ALIASES,
)
from .cache import DEFAULT_CACHE_TTL, SnapshotCache
from .data import CurrencyEntry, CurrencySnapshot
from .graph import render_graph_block


@dataclass
class TrackerConfig:
    league: str
    category: str = "Currency"
    game: str = "poe2"
    limit: int = 15
    refresh_interval: float = 120.0
    poe_ninja_cookie: Optional[str] = None


@dataclass(slots=True)
class DisplayEntry:
    category: str
    normalized_category: str
    entry: CurrencyEntry


class TrackerUI:
    """Encapsulates the curses rendering and event loop."""

    def __init__(self, config: TrackerConfig) -> None:
        self.config = config
        self.snapshot: Optional[CurrencySnapshot] = None
        self.error_message: Optional[str] = None
        self.selected_index = 0
        self.last_refresh = 0.0
        self.should_exit = False
        self.category_cycle = self._build_category_cycle()
        self.category_index = self._locate_category_index(self.config.category)
        if self.category_cycle:
            self.config.category = self.category_cycle[self.category_index]
        cache_ttl = max(self.config.refresh_interval, DEFAULT_CACHE_TTL)
        self.snapshot_cache = SnapshotCache(ttl=cache_ttl)
        self._force_refresh = False
        self.info_message: Optional[tuple[str, float]] = None
        self.search_active = False
        self.search_query = ""
        self.search_results: list[DisplayEntry] = []
        self.scroll_offset = 0
        self._exalt_baseline: Optional[float] = None

    def run(self, stdscr: "curses._CursesWindow") -> None:
        self._initialize_curses(stdscr)
        try:
            while not self.should_exit:
                now = time.time()
                force_refresh = self._force_refresh
                if (
                    force_refresh
                    or self.snapshot is None
                    or (now - self.last_refresh) >= self.config.refresh_interval
                ):
                    self._refresh_data(force=force_refresh)
                    self._force_refresh = False
                self._render(stdscr)
                self._handle_input(stdscr)
        finally:
            self._teardown_curses()

    def _initialize_curses(self, stdscr: "curses._CursesWindow") -> None:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.nodelay(True)
        stdscr.keypad(True)
        stdscr.timeout(200)

        if curses.has_colors():
            curses.start_color()
            curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)  # header
            curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)  # positive
            curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)  # negative
            curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_CYAN)  # selected row
            curses.init_pair(5, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # warnings

    def _teardown_curses(self) -> None:
        curses.flushinp()

    def _build_category_cycle(self) -> list[str]:
        if self.config.game.lower() != "poe2":
            return []
        ordered: list[str] = []
        seen: set[str] = set()
        for name in POE2_FALLBACK_OVERVIEWS:
            cleaned = name.strip()
            norm = self._normalize_category(cleaned)
            if cleaned and norm not in seen:
                ordered.append(cleaned)
                seen.add(norm)
        for variants in POE2_OVERVIEW_ALIASES.values():
            if not variants:
                continue
            display = variants[0].strip()
            norm = self._normalize_category(display)
            if display and norm not in seen:
                ordered.append(display)
                seen.add(norm)
        current = self.config.category.strip()
        if current:
            normalized_current = self._normalize_category(current)
            if all(self._normalize_category(item) != normalized_current for item in ordered):
                ordered.append(current)
        return ordered

    @staticmethod
    def _normalize_category(value: Optional[str]) -> str:
        return (value or "").strip().lower()

    def _locate_category_index(self, category: str) -> int:
        if not self.category_cycle:
            return 0
        normalized = self._normalize_category(category)
        for idx, item in enumerate(self.category_cycle):
            if self._normalize_category(item) == normalized:
                return idx
        cleaned = category.strip() or "Currency"
        self.category_cycle.append(cleaned)
        return len(self.category_cycle) - 1

    def _refresh_data(self, force: bool = False) -> None:
        normalized_category = self._normalize_category(self.config.category)
        now = time.time()

        cached_snapshot = self.snapshot_cache.get(normalized_category)
        if cached_snapshot and not force:
            self._ensure_exalted_values(cached_snapshot)
            self.snapshot = cached_snapshot
            self.selected_index = min(self.selected_index, max(0, len(cached_snapshot.entries) - 1))
            self.error_message = None
            self.last_refresh = now
            self._refresh_search_results()
            return

        try:
            snapshot = fetch_currency_snapshot(
                self.config.league,
                self.config.category,
                game=self.config.game,
                ninja_cookie=self.config.poe_ninja_cookie,
            )
            self._ensure_exalted_values(snapshot)
            self.snapshot = snapshot
            self.snapshot_cache.set(normalized_category, snapshot)
            self.selected_index = min(self.selected_index, max(0, len(snapshot.entries) - 1))
            self.error_message = None
            self.last_refresh = now
            self._refresh_search_results()
        except ApiError as exc:
            self.error_message = f"Fetch failed: {exc}"
            self.last_refresh = now
            self.snapshot_cache.remove(normalized_category)
            if "No data returned" in str(exc) and self._remove_category(normalized_category):
                self.error_message = None
                return

    def _handle_input(self, stdscr: "curses._CursesWindow") -> None:
        key = stdscr.getch()
        if key == -1:
            return
        if key == 27:  # Escape
            if self.search_query or self.search_active:
                self._clear_search()
                return
        if self.search_active:
            if self._process_search_key(key):
                return
        elif key == ord("/"):
            self._start_search()
            return
        elif self.search_query:
            # Allow continued incremental search even after leaving capture mode.
            if self._process_search_key(key):
                return
        if key in (ord("q"), ord("Q")):
            self.should_exit = True
            return
        if key in (ord("r"), ord("R")):
            self._force_refresh = True
            self.last_refresh = 0.0
            return
        if key in (curses.KEY_DOWN, ord("j")):
            self._move_selection(1)
            return
        if key in (curses.KEY_UP, ord("k")):
            self._move_selection(-1)
            return
        if key == curses.KEY_RIGHT:
            self._cycle_category(1)
            return
        if key == curses.KEY_LEFT:
            self._cycle_category(-1)
            return
        if key in (curses.KEY_NPAGE,):
            self._move_selection(5)
            return
        if key in (curses.KEY_PPAGE,):
            self._move_selection(-5)
            return

    def _move_selection(self, delta: int) -> None:
        entries = self._current_entries()
        if not entries:
            return
        self.selected_index = max(0, min(self.selected_index + delta, len(entries) - 1))

    def _cycle_category(self, delta: int) -> None:
        if not self.category_cycle:
            return
        original_index = self.category_index
        for _ in range(len(self.category_cycle)):
            next_index = (self.category_index + delta) % len(self.category_cycle)
            target = self.category_cycle[next_index]
            if self._switch_category(target):
                return
            self.category_index = next_index
        self.category_index = original_index

    def _switch_category(self, category_name: str, prefer_cache: bool = True) -> bool:
        normalized = self._normalize_category(category_name)
        if not category_name:
            return False
        if self._normalize_category(self.config.category) == normalized and self.snapshot:
            return True
        self.category_index = self._locate_category_index(category_name)
        self.config.category = self.category_cycle[self.category_index]
        self.selected_index = 0
        if prefer_cache:
            cached = self._get_cached_snapshot(normalized)
            if cached is not None:
                self.snapshot = cached
                self.selected_index = min(self.selected_index, max(0, len(cached.entries) - 1))
                self.error_message = None
                self.last_refresh = time.time()
                return True
        self.snapshot = None
        self.last_refresh = 0.0
        self._refresh_data()
        return self.snapshot is not None

    def _remove_category(self, normalized_category: str) -> bool:
        if not self.category_cycle:
            return False
        for idx, name in enumerate(list(self.category_cycle)):
            if self._normalize_category(name) == normalized_category:
                self.category_cycle.pop(idx)
                self.snapshot_cache.remove(normalized_category)
                if not self.category_cycle:
                    self.config.category = ""
                    self.snapshot = None
                    self._set_info_message(f"Removed category '{name}' (no data)")
                    return False
                self.category_index = idx % len(self.category_cycle)
                self.config.category = self.category_cycle[self.category_index]
                self.snapshot = None
                self.selected_index = 0
                self.last_refresh = 0.0
                self._set_info_message(f"Removed category '{name}' (no data)")
                return True
        return False

    def _get_cached_snapshot(self, normalized_category: str) -> Optional[CurrencySnapshot]:
        snapshot = self.snapshot_cache.get(normalized_category)
        if snapshot:
            self._ensure_exalted_values(snapshot)
        return snapshot

    def _start_search(self) -> None:
        if not self.search_active:
            self.search_active = True
            self.scroll_offset = 0
            self._set_info_message("Search mode active (Esc to clear)")
        self._refresh_search_results()

    def _process_search_key(self, key: int) -> bool:
        if key in (curses.KEY_BACKSPACE, curses.KEY_DC, 127, 8):
            if self.search_query:
                self._update_search_query(self.search_query[:-1])
            else:
                self._clear_search()
            return True
        if key in (curses.KEY_ENTER, 10, 13):
            self.search_active = False
            return True
        if 32 <= key <= 126:
            self._update_search_query(self.search_query + chr(key))
            return True
        return False

    def _update_search_query(self, query: str) -> None:
        if query == self.search_query:
            return
        self.search_query = query
        if self.search_query:
            self.search_results = self._collect_search_results(self.search_query)
            self.selected_index = 0
        else:
            self.search_results = []
        self.scroll_offset = 0
        self._clamp_selection()

    def _clear_search(self) -> None:
        if not self.search_query and not self.search_active:
            return
        self.search_query = ""
        self.search_results = []
        self.search_active = False
        self.scroll_offset = 0
        self._clamp_selection()
        self._set_info_message("Search cleared")

    def _collect_search_results(self, query: str) -> list[DisplayEntry]:
        if not query:
            return []
        needle = query.lower()
        matches: list[DisplayEntry] = []
        for normalized, snapshot in self.snapshot_cache.items():
            self._ensure_exalted_values(snapshot)
            display_name = self._category_display_name(normalized)
            for entry in snapshot.entries:
                if needle in entry.name.lower():
                    matches.append(DisplayEntry(display_name, normalized, entry))
        matches.sort(key=lambda item: item.entry.chaos_value, reverse=True)
        limit = max(self.config.limit, 1)
        return matches[:limit]

    def _refresh_search_results(self) -> None:
        if not self.search_query:
            return
        current_index = self.selected_index
        self.search_results = self._collect_search_results(self.search_query)
        if self.search_results:
            self.selected_index = max(0, min(current_index, len(self.search_results) - 1))
        else:
            self.selected_index = 0
        self.scroll_offset = min(self.scroll_offset, max(0, len(self.search_results) - 1))
        self._clamp_selection()

    def _current_entries(self) -> list[DisplayEntry]:
        if self.search_query:
            return self.search_results
        if not self.snapshot or not self.snapshot.entries:
            return []
        normalized = self._normalize_category(self.config.category)
        display_name = self._category_display_name(normalized)
        entries = self.snapshot.top_entries(self.config.limit)
        return [DisplayEntry(display_name, normalized, entry) for entry in entries]

    def _format_entry_label(self, display: DisplayEntry) -> str:
        name = display.entry.name
        if display.normalized_category == "uncutgems":
            name = re.sub(r"\bLevel\b", "Lvl", name)
        return name

    def _category_display_name(self, normalized_category: str) -> str:
        for name in self.category_cycle:
            if self._normalize_category(name) == normalized_category:
                return name
        if self.config.category and self._normalize_category(self.config.category) == normalized_category:
            return self.config.category
        return normalized_category.capitalize()

    def _clamp_selection(self) -> None:
        entries = self._current_entries()
        if not entries:
            self.selected_index = 0
            self.scroll_offset = 0
            return
        self.selected_index = max(0, min(self.selected_index, len(entries) - 1))
        self.scroll_offset = max(0, min(self.scroll_offset, max(0, len(entries) - 1)))

    def _compute_exalted_values(self, entries: List[CurrencyEntry]) -> None:
        exalt_price = self._extract_exalt_price(entries)
        if exalt_price is None:
            exalt_price = self._get_currency_baseline()
        else:
            self._exalt_baseline = exalt_price
        if exalt_price is None or exalt_price <= 0:
            return
        for entry in entries:
            entry.exalt_value = (entry.chaos_value / exalt_price) if entry.chaos_value else None

    def _extract_exalt_price(self, entries: List[CurrencyEntry]) -> Optional[float]:
        def _maybe_update(current: Optional[float], candidate: float) -> float:
            if current is None or candidate < current:
                return candidate
            return current

        best: Optional[float] = None
        for entry in entries:
            if entry.chaos_value <= 0:
                continue
            details = (entry.details_id or "").strip().lower()
            if details == "exalted-orb":
                best = _maybe_update(best, entry.chaos_value)
        if best is not None:
            return best

        for entry in entries:
            if entry.chaos_value <= 0:
                continue
            normalized_name = entry.name.strip().lower()
            if normalized_name == "exalted orb":
                best = _maybe_update(best, entry.chaos_value)
        return best

    def _find_exalt_price_from_cache(self) -> Optional[float]:
        best: Optional[float] = None
        for _, snapshot in self.snapshot_cache.items():
            price = self._extract_exalt_price(snapshot.entries)
            if price:
                best = price
                break
        return best

    def _get_currency_baseline(self) -> Optional[float]:
        currency_snapshot = self.snapshot_cache.get("currency")
        if currency_snapshot:
            price = self._extract_exalt_price(currency_snapshot.entries)
            if price:
                self._exalt_baseline = price
                return price
        return self._exalt_baseline

    def _ensure_exalted_values(self, snapshot: CurrencySnapshot) -> None:
        if not snapshot or not snapshot.entries:
            return
        self._compute_exalted_values(snapshot.entries)

    def _set_info_message(self, message: str) -> None:
        if not message:
            self.info_message = None
        else:
            self.info_message = (message, time.time())

    def _render(self, stdscr: "curses._CursesWindow") -> None:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        self._render_header(stdscr, width)
        table_width = max(50, int(width * 0.6))
        graph_width = width - table_width - 3
        table_height = height - 4
        graph_height = table_height
        graph_height = max(3, min(graph_height, 20))

        table_y = 1
        table_x = 1
        graph_x = table_x + table_width + 1

        self._render_table(stdscr, table_y, table_x, table_width, table_height)
        self._render_graph(stdscr, table_y, graph_x, graph_width, graph_height)
        self._render_status(stdscr, height - 2, width)
        stdscr.refresh()

    def _render_header(self, stdscr: "curses._CursesWindow", width: int) -> None:
        game_label = "PoE 2" if self.config.game.lower() == "poe2" else "PoE"
        title = f" Path of Exile Currency Tracker [{game_label}] - {self.config.league} ({self.config.category}) "
        padded = title.center(width, " ")
        attributes = curses.color_pair(1) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
        self._addstr(stdscr, 0, 0, padded[:width], attributes)

    def _render_table(
        self,
        stdscr: "curses._CursesWindow",
        start_y: int,
        start_x: int,
        width: int,
        height: int,
    ) -> None:
        if height <= 0 or width <= 0:
            return
        label_attr = curses.A_UNDERLINE
        if curses.has_colors():
            label_attr |= curses.color_pair(1)
        if self.search_query:
            label_text = f"Search: {self.search_query}"
        else:
            label_text = f"Category: {self.config.category}" if self.config.category else "Category"
        self._addstr(stdscr, start_y, start_x, label_text[:width], label_attr)

        header_y = start_y + 1
        if header_y >= start_y + height:
            return

        headers = ["Rank", "Currency", "Exalted", "Chaos", "Divine", "Volume/Hour"]
        column_widths = self._calculate_column_widths(width, headers)
        header_line = self._format_row(headers, column_widths)
        attributes = curses.A_BOLD
        if curses.has_colors():
            attributes |= curses.color_pair(1)
        self._addstr(stdscr, header_y, start_x, header_line[:width], attributes)

        data_start = header_y + 1

        entries = self._current_entries()
        if not entries:
            if self.search_query:
                message = f"No matches for '{self.search_query}'"
            else:
                message = "Waiting for data..." if not self.error_message else self.error_message
            self._draw_message_block(stdscr, data_start, start_x, width, height - (data_start - start_y), message)
            return

        window_capacity = max(1, start_y + height - data_start)
        total_entries = len(entries)
        self.scroll_offset = max(0, min(self.scroll_offset, max(0, total_entries - 1)))
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + window_capacity:
            self.scroll_offset = self.selected_index - window_capacity + 1
        self.scroll_offset = max(0, min(self.scroll_offset, max(0, total_entries - window_capacity)))

        visible_slice = entries[self.scroll_offset : self.scroll_offset + window_capacity]
        for offset, display in enumerate(visible_slice):
            row_index = data_start + offset
            if row_index >= start_y + height:
                break
            actual_index = self.scroll_offset + offset
            entry = display.entry
            name = self._format_entry_label(display)
            cells = [
                f"{actual_index + 1}",
                name,
                entry.formatted_exalt(),
                entry.formatted_chaos(),
                entry.formatted_divine(),
                f"{entry.trade_count:,}" if entry.trade_count else "--",
            ]
            row_text = self._format_row(cells, column_widths)
            attributes = curses.A_NORMAL
            if actual_index == self.selected_index:
                if curses.has_colors():
                    attributes |= curses.color_pair(4)
                else:
                    attributes |= curses.A_REVERSE
            self._addstr(stdscr, row_index, start_x, row_text[:width], attributes)

    def _render_graph(
        self,
        stdscr: "curses._CursesWindow",
        start_y: int,
        start_x: int,
        width: int,
        height: int,
    ) -> None:
        if width <= 0 or height <= 3:
            return
        entries = self._current_entries()
        if not entries:
            self._draw_message_block(
                stdscr,
                start_y,
                start_x,
                width,
                height,
                "Graph will appear after data is loaded." if not self.search_query else "No matching data for graph.",
            )
            return

        index = max(0, min(self.selected_index, len(entries) - 1))
        selected_entry = entries[index]
        available_height = height - 1
        if available_height <= 0:
            return
        graph_lines = render_graph_block(selected_entry.entry.sparkline, width, available_height)
        display_name = self._format_entry_label(selected_entry)
        label = f" {display_name} price trend (receive, 7-day sparkline) "
        if self.search_query:
            label = f" {display_name} [{selected_entry.category}] price trend (receive, 7-day sparkline) "
        label = label[: width - 2]
        attributes = curses.A_BOLD
        if curses.has_colors():
            attributes |= curses.color_pair(1)
        self._addstr(stdscr, start_y, start_x, label.ljust(width), attributes)
        for idx, line in enumerate(graph_lines):
            if idx >= available_height:
                break
            self._addstr(stdscr, start_y + 1 + idx, start_x, line[:width])

    def _render_status(self, stdscr: "curses._CursesWindow", y: int, width: int) -> None:
        if y < 0:
            return
        if self.snapshot or self.search_query:
            last_update = time.strftime("%H:%M:%S", time.localtime(self.snapshot.fetched_at)) if self.snapshot else "--:--:--"
            controls = "q=quit r=refresh ↑/↓=rows PgUp/PgDn=±5 /=search Esc=clear"
            if self.category_cycle:
                controls += " ←/→=category"
            status = f"Last update: {last_update} | Refresh: {int(self.config.refresh_interval)}s | {controls}"
            if self.search_query:
                entries = self._current_entries()
                status += f" | Filter: {self.search_query} ({len(entries)} items)"
        else:
            status = "Connecting to PoE Ninja..."
        if self.info_message:
            message, ts = self.info_message
            if time.time() - ts < 6:
                status += f" | {message}"
            else:
                self.info_message = None
        if self.error_message:
            error_text = f" | {self.error_message}"
            status = status + error_text
        line = status[:width].ljust(width)
        attributes = curses.A_DIM
        if self.error_message and curses.has_colors():
            attributes = curses.color_pair(5) | curses.A_BOLD
        self._addstr(stdscr, y, 0, line, attributes)

    def _draw_message_block(
        self,
        stdscr: "curses._CursesWindow",
        start_y: int,
        start_x: int,
        width: int,
        height: int,
        message: str,
    ) -> None:
        if height <= 0:
            return
        lines = self._wrap_text(message, width)
        block_height = min(len(lines), height)
        offset_y = start_y + max(0, (height - block_height) // 2)
        for idx in range(block_height):
            text = lines[idx][:width].center(width, " ")
            self._addstr(stdscr, offset_y + idx, start_x, text)

    @staticmethod
    def _format_row(cells: list[str], widths: list[int]) -> str:
        padded = []
        for cell, width in zip(cells, widths):
            truncated = cell[:width].ljust(width)
            padded.append(truncated)
        return " ".join(padded)

    @staticmethod
    def _calculate_column_widths(total_width: int, headers: list[str]) -> list[int]:
        base_widths = {
            "Rank": 2,
            "Currency": 30,
            "Exalted": 12,
            "Chaos": 12,
            "Divine": 10,
            "Trades": 9,
        }
        preferred = [max(base_widths.get(header, len(header) + 2), len(header) + 1) for header in headers]
        padding = len(headers) - 1
        min_total = sum(preferred) + padding
        if total_width <= min_total:
            # scale down proportionally but keep at least 3 chars per column
            available = max(total_width - padding, len(headers) * 3)
            scaled = []
            total_pref = sum(preferred)
            remaining = available
            for idx, pref in enumerate(preferred):
                if idx == len(preferred) - 1:
                    width = max(3, remaining)
                else:
                    width = max(3, (pref * available) // total_pref)
                    remaining -= width
                scaled.append(width)
            return scaled

        widths = preferred[:]
        extra = total_width - min_total
        priority_names = ["Currency", "Exalted", "Chaos", "Divine", "Trades", "Rank"]
        allocation_order = [headers.index(name) for name in priority_names if name in headers]
        if not allocation_order:
            allocation_order = list(range(len(headers)))
        idx = 0
        while extra > 0:
            column = allocation_order[idx % len(allocation_order)]
            widths[column] += 1
            extra -= 1
            idx += 1
        return widths

    @staticmethod
    def _wrap_text(text: str, width: int) -> list[str]:
        if width <= 0:
            return []
        words = text.split()
        if not words:
            return [""]
        lines = []
        current = words[0]
        for word in words[1:]:
            if len(current) + 1 + len(word) <= width:
                current += " " + word
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    @staticmethod
    def _addstr(window: "curses._CursesWindow", y: int, x: int, text: str, attributes: int = 0) -> None:
        try:
            window.addstr(y, x, text, attributes)
        except curses.error:
            pass
