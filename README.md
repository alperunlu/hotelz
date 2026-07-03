# Hotel Contact Info Scraper

Scrapes hotel names, ratings, addresses, phone numbers, and websites from Google Maps using Playwright.

## Features

- GUI mode (tkinter) with progress log and results table
- CLI mode for headless/scheduled runs
- Exports to CSV (`hotels_{city}_{date}.csv`)

## Requirements

- Python 3.8+
- `playwright` (install browsers with `playwright install chromium`)

## Usage

```bash
# GUI mode (no args)
python scraper.py

# CLI mode
python scraper.py "New York"
