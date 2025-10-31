from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence


@dataclass(slots=True)
class CurrencyEntry:
    """Represents a single currency line from the PoE Ninja overview."""

    name: str
    chaos_value: float
    divine_value: Optional[float] = None
    exalt_value: Optional[float] = None
    change_percent: Optional[float] = None
    sparkline: Sequence[float] = field(default_factory=list)
    trade_count: Optional[int] = None
    details_id: Optional[str] = None
    icon_url: Optional[str] = None

    def formatted_change(self) -> str:
        if self.change_percent is None:
            return "--"
        return f"{self.change_percent:+.1f}%"

    def formatted_chaos(self) -> str:
        return self._format_number(self.chaos_value, 1)

    def formatted_divine(self) -> str:
        return self._format_number(self.divine_value, 2)

    def formatted_exalt(self) -> str:
        return self._format_number(self.exalt_value, 2)

    @staticmethod
    def _format_number(value: Optional[float], decimals: int, integer_threshold: float = 100.0) -> str:
        if value is None:
            return "--"
        if abs(value) >= integer_threshold:
            return f"{int(round(value)):,}"
        formatted = f"{value:,.{decimals}f}"
        if "." in formatted:
            formatted = formatted.rstrip("0").rstrip(".")
        return formatted


@dataclass(slots=True)
class CurrencySnapshot:
    """A snapshot of the currency overview for a specific league."""

    league: str
    entries: List[CurrencyEntry]
    fetched_at: float
    source_type: str

    def top_entries(self, limit: int) -> List[CurrencyEntry]:
        return self.entries[:limit]
