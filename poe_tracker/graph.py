from __future__ import annotations

from typing import Iterable, List, Sequence


def downsample_series(series: Sequence[float], target_width: int) -> List[float]:
    """Downsample or interpolate a series to a target width."""
    if not series:
        return []
    if target_width <= 0:
        return []
    if len(series) <= target_width:
        # simple linear interpolation to expand to width
        if len(series) == target_width:
            return list(series)
        if len(series) == 1:
            return [series[0]] * target_width
        step = (len(series) - 1) / (target_width - 1)
        result: List[float] = []
        for idx in range(target_width):
            pos = idx * step
            left = int(pos)
            right = min(left + 1, len(series) - 1)
            weight = pos - left
            value = series[left] * (1 - weight) + series[right] * weight
            result.append(value)
        return result

    step = (len(series) - 1) / (target_width - 1)
    result = []
    for idx in range(target_width):
        pos = idx * step
        left = int(pos)
        right = min(left + 1, len(series) - 1)
        weight = pos - left
        result.append(series[left] * (1 - weight) + series[right] * weight)
    return result


def scale_series(series: Sequence[float], height: int) -> List[int]:
    """Scale a numeric series into integer bands fitting the provided height."""
    if height <= 0:
        return []
    if not series:
        return []
    low = min(series)
    high = max(series)
    if high == low:
        middle = height // 2
        return [middle] * len(series)
    scale = (height - 1) / (high - low)
    return [int(round((value - low) * scale)) for value in series]


def render_line_chart(series: Sequence[float], width: int, height: int) -> List[str]:
    """Render a bordered ASCII line chart with value markers."""
    clean_series = [value for value in series if value is not None]  # type: ignore[arg-type]
    if not clean_series or width <= 2 or height <= 2:
        return [" " * width for _ in range(max(height, 1))]

    inner_width = max(width - 2, 1)
    inner_height = max(height - 2, 1)

    sampled = downsample_series(clean_series, inner_width)
    scaled = scale_series(sampled, inner_height)
    low = min(clean_series)
    high = max(clean_series)
    mid = (low + high) / 2 if high != low else low

    grid = [[" " for _ in range(inner_width)] for _ in range(inner_height)]
    for idx, band in enumerate(scaled):
        row = inner_height - 1 - band
        grid[row][idx] = "●"
        if idx == 0:
            continue
        prev_band = scaled[idx - 1]
        prev_row = inner_height - 1 - prev_band
        if prev_row == row:
            grid[row][idx - 1] = "•"
        else:
            step = 1 if row < prev_row else -1
            char = "/" if row < prev_row else "\\"
            for intermediate in range(prev_row + step, row, step):
                grid[intermediate][idx - 1] = char

    lines = []
    top_label = f"{high:,.1f}".ljust(inner_width)
    lines.append("┌" + top_label + "┐")
    for row_idx, row in enumerate(grid):
        if inner_height >= 3 and row_idx == inner_height // 2:
            label = f"{mid:,.1f}"
            row_text = "".join(row)
            row_text = label[: min(len(label), inner_width)].ljust(inner_width)
        else:
            row_text = "".join(row)
        lines.append("│" + row_text + "│")
    bottom_label = f"{low:,.1f}".ljust(inner_width)
    lines.append("└" + bottom_label + "┘")
    return lines


def format_axis(low: float, high: float, width: int) -> str:
    """Create an axis label row describing low/high values."""
    low_text = f"min {low:,.1f}"
    high_text = f"max {high:,.1f}"
    if width < len(low_text) + len(high_text) + 1:
        return (low_text + " " + high_text)[:width].ljust(width)
    spacer = width - len(low_text) - len(high_text)
    return f"{low_text}{' ' * spacer}{high_text}"


def render_graph_block(series: Sequence[float], width: int, height: int) -> List[str]:
    """Render a graph block including axis information."""
    clean_series = [value for value in series if value is not None]  # type: ignore[arg-type]
    if not clean_series:
        return [" " * width for _ in range(max(1, height))]
    if height <= 1:
        return render_line_chart(clean_series, width, 1)
    chart_height = height - 1
    chart = render_line_chart(clean_series, width, chart_height)
    low = min(clean_series)
    high = max(clean_series)
    axis = format_axis(low, high, width)
    return chart + [axis]
