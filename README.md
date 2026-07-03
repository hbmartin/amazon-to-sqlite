# amazon-to-sqlite

[![PyPI](https://img.shields.io/pypi/v/amazon-to-sqlite.svg)](https://pypi.org/project/amazon-to-sqlite/)
[![Lint](https://github.com/hbmartin/amazon-to-sqlite/actions/workflows/lint.yml/badge.svg)](https://github.com/hbmartin/amazon-to-sqlite/actions/workflows/lint.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Save your Amazon.com order history to a SQLite database, ready to explore with
[Datasette](https://datasette.io/) or plain SQL.

## Getting your data from Amazon

1. Go to Amazon's [Request My Data](https://www.amazon.com/hz/privacy-central/data-requests/preview.html)
   page (Account → Privacy Central → Request My Data).
2. Request **Your Orders** (or all of your data).
3. Amazon emails you a link within a few days. Download and unzip the archive.
4. Your order history lives in files named like `Retail.OrderHistory.1.csv`.

## Installation

```bash
pip install amazon-to-sqlite
```

## Usage

Import one or more CSV files — or point it at the unzipped export directory
and it will find every CSV in there:

```bash
amazon-to-sqlite import Retail.OrderHistory.1.csv
amazon-to-sqlite import path/to/unzipped-export/ --db amazon.db
```

Order-history files are loaded into an `amazon_orders` table. Any other CSV
in the export (digital orders, returns, refunds, ...) is loaded into its own
table named after the file (`Digital Items.csv` → `digital_items`).

Options:

- `--db PATH` — database file to write to (default `amazon.db`)
- `--replace` — drop existing destination tables before importing
- `-q` / `--quiet` — suppress the progress bar and summary
- `--version` — print the version and exit

Imports are **idempotent**: rows are deduplicated with a unique index, so
re-running the tool on the same (or an updated) export only adds new rows.

### Checking book formats

List the print books in your order history (ASINs that are valid ISBN-10s)
and check amazon.com for other available formats (Kindle, audiobook, ...):

```bash
amazon-to-sqlite check-formats            # every print book in amazon.db
amazon-to-sqlite check-formats 1098168100 # or specific ASINs
```

Note that scraping amazon.com is best-effort; Amazon changes its markup often
and rate-limits automated requests.

## Data notes

- **Dates** (`Order_Date`, `Ship_Date`) are normalized to ISO 8601 strings so
  they sort and filter correctly in SQL.
- **Money** columns (`Unit_Price`, `Total_Owed`, ...) are parsed (currency
  symbols and thousands separators stripped) and stored as SQLite `REAL`
  values — convenient for `SUM()` in queries, with usual binary-float caveats.
- `Not Applicable` / `Not Available` values are stored as `NULL`.
- Column headers are matched **by name**, so Amazon reordering or adding
  columns won't corrupt an import; a missing expected column fails loudly.
- Indexes are created on `Order_Date`, `ASIN` and `Order_Status`, plus a
  full-text search index on `Product_Name` (`amazon_orders_fts`).

## Exploring with Datasette

```bash
pip install datasette
datasette amazon.db -m metadata.json
```

The bundled [`metadata.json`](metadata.json) includes canned queries such as
spend by year, spend by month, top products, and orders by status. Full-text
search product names with:

```sql
SELECT * FROM amazon_orders
WHERE rowid IN (
    SELECT rowid FROM amazon_orders_fts WHERE amazon_orders_fts MATCH 'coffee'
);
```

## Development

```bash
git clone https://github.com/hbmartin/amazon-to-sqlite
cd amazon-to-sqlite
pip install -e '.[lint]'

pytest                          # run the tests
ruff check amazon_to_sqlite     # lint
ruff format --check .           # formatting
mypy amazon_to_sqlite           # type-check
```

## License

[Apache 2.0](LICENSE)
