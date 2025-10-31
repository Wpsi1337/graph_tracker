# PoE Currency Tracker

Lightweight curses terminal UI for visualising Path of Exile currency prices via the PoE Ninja API.

## Features

- Live currency overview for both Path of Exile 1 and Path of Exile 2 leagues
- Built‑in category catalogue for PoE1 (Currency, Fragment, BaseType, UniqueWeapon, …) so new tabs work instantly
- Stash vs. exchange price mode toggle for PoE1 (falls back automatically if exchange data is unavailable)
- Refresh interval control to remain polite to the public API
- Keyboard navigation with highlighted selection
- `/` search that doubles as an instant category jump (press <kbd>Enter</kbd> to switch to the matching overview)
- Inline ASCII sparkline showing recent trend for the selected currency
- Minimal dependencies: relies solely on the Python standard library

![Currency overview screenshot](images/currency_view.png)
![Omen overview screenshot](images/omen_view.png)
## Requirements

- Python 3.10 or later
- Unix-like terminal with basic colour support (tested on Arch Linux)
- Network access to `https://poe.ninja`

## Usage

```bash
python -m poe_tracker --league "Rise of the Abyssal" --category Currency --limit 35 --interval 120
```

Arguments:

- `--league`: target Path of Exile league (default `Rise of the Abyssal`)
- `--category`: PoE Ninja overview category (`Currency`, `Fragment`, `UniqueWeapon`, …)
- `--game`: set `poe2` (default) or `poe` for the original client
- `--ninja-cookie`: optional PoE.Ninja session cookie (or set `POE_NINJA_COOKIE`) for authenticated endpoints
- `--limit`: number of currencies to list
- `--interval`: refresh cadence in seconds (minimum 10s)

## Key Bindings

- `↑` / `j`: move selection up
- `↓` / `k`: move selection down
- `PgUp` / `PgDn`: jump several rows
- `←` / `→`: cycle categories
- `Tab`: toggle between *Stash* and *Exchange* pricing (PoE1 only; automatically falls back to stash when exchange data is unavailable)
- `r`: force refresh
- `q`: quit
- `/`: search entries (press <kbd>Enter</kbd> on a query such as `currency` or `basetype` to jump directly to that category)
- `Esc`: clear search
## Notes

- The PoE Ninja API enforces rate limits; the tool defaults to a 120 second refresh to stay within limits.
- When the API is unreachable, the status bar reports the failure and the UI continues to retry on the configured cadence.
- Exchange endpoints for very new leagues can return `404`. The tracker will show an info message and stick to stash data until exchange prices become available.
