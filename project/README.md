# Attijari Bank Tunisia Branch Scraper

Production-style Python 3.12 scraper for the public Attijari Bank Tunisia branch directory:

- Scrapes all branches from `https://www.attijaribank.com.tn/fr/reseaux-dagence`.
- Respects `robots.txt` and uses polite delays.
- Uses **requests + BeautifulSoup** when possible, and automatically falls back to **Playwright** when dynamic rendering is required.
- Cleans and deduplicates records.
- Exports data to **CSV**, **Excel (.xlsx)**, **JSON**.
- Optionally inserts data into **PostgreSQL**.

## Project structure

```text
project/
├── scraper.py        # Orchestrator: scraping, exports, PostgreSQL insert, summary
├── parser.py         # HTML parsing, text normalisation, deduplication
├── database.py       # PostgreSQL table creation and batch inserts
├── config.py         # URLs, settings, output paths, DB config loader
├── requirements.txt  # Python dependencies
├── README.md         # This file
└── output/           # Generated files (created at runtime)
    ├── branches.csv
    ├── branches.xlsx
    └── branches.json
```

## Prerequisites

- Python **3.12**
- PostgreSQL instance (optional but recommended for full functionality)

## Installation

From the `project/` directory:

```bash
pip install -r requirements.txt
python -m playwright install
```

The `playwright install` step downloads the required browser binaries.

## Database configuration

Create a `.env` file inside `project/` if you want to insert the scraped data into PostgreSQL:

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=attijari
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password
```

If any of these variables are missing, the scraper will still run and write CSV / XLSX / JSON, but it will skip database insertion.

## Running the scraper

From inside the `project/` directory:

```bash
python scraper.py
```

The script will:

1. Read `robots.txt` and verify that `/fr/reseaux-dagence` is allowed.
2. Attempt to load the directory page using **requests**.
3. Parse the HTML; if branches are found, continue in requests mode.
4. If not, fall back to **Playwright** to render the page and retry parsing.
5. Discover any additional pages (pagination) and scrape them all.
6. Clean and normalise text fields (spaces, Unicode normalisation for French characters).
7. Remove duplicate branches based on `(name, address, postal code, city)`.
8. Export the final dataset to:
   - `output/branches.csv`
   - `output/branches.xlsx`
   - `output/branches.json`
9. Create the `branches` table in PostgreSQL (if DB config is present) and insert the records.
10. Print a summary with:
    - number of branches scraped
    - number of cities
    - number of duplicate records removed
    - rows inserted into PostgreSQL

## Notes and customisation

- If the Attijari site changes its HTML structure, adjust the CSS selectors in `parser.py` to match the new layout.
- The de-duplication logic is implemented in `parser.deduplicate_branches` and can be tuned if needed.
- Timeouts, retry counts, and polite delays are configurable in `config.py`.

