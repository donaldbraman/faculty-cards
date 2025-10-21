# Faculty Cards

A Python pipeline that scrapes structured faculty data from the GW Law full-time faculty directory and automatically generates Anki flashcard decks with photo-front cards.

## Features

- **Web Scraping**: Extracts faculty information from https://www.law.gwu.edu/full-time-faculty
- **Data Collection**: Gathers names, titles, photos, bios, and recent publications
- **Photo Management**: Downloads and caches faculty headshots
- **Dual Export**: Generates both CSV and Anki package (.apkg) files
- **Respectful Scraping**: Implements rate limiting and request throttling

## Requirements

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

## Installation

### Using uv (recommended)

```bash
uv sync
```

### Using pip

```bash
pip install -r requirements.txt
```

## Usage

Run the scraper:

```bash
python gw_law_cards.py
```

Or using uv:

```bash
uv run gw_law_cards.py
```

### Output

The script creates an `out/` directory containing:

- `gwlaw_faculty.csv` - CSV file for manual Anki import
- `gwlaw_faculty.apkg` - Ready-to-use Anki deck
- `media/` - Downloaded faculty photos

### Anki Card Structure

- **Front**: Faculty photo only
- **Back**: Name, title, biography, and latest publications (up to 3)

## How It Works

1. **Directory Scraping**: Iterates through paginated faculty directory
2. **Profile Extraction**: Visits each faculty member's profile page
3. **Data Parsing**: Extracts biographical information and publications
4. **Image Download**: Downloads and caches faculty photos
5. **Export**: Generates CSV and Anki package with embedded media

## Technical Details

- **Rate Limiting**: 1.5-3 second delays between requests
- **Deduplication**: Automatically handles duplicate entries
- **Error Handling**: Logs incomplete records and missing data
- **Image Caching**: Uses SHA-1 hashing to avoid re-downloading images

## Dependencies

- `requests` - HTTP client
- `beautifulsoup4` - HTML parsing
- `genanki` - Anki package generation

## License

See LICENSE file for details.

## Purpose

Automates end-to-end data acquisition and flashcard generation for academic study or internal directory reference.
