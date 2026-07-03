"""Command line interface for amazon-to-sqlite."""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from tqdm import tqdm

from amazon_to_sqlite import __version__, db
from amazon_to_sqlite.check_book_formats import check_book_formats
from amazon_to_sqlite.importer import (
    EmptyCsvError,
    HeaderMismatchError,
    expand_paths,
    import_file,
    peek_table_name,
)

if TYPE_CHECKING:
    from sqlite3 import Connection

DEFAULT_DB = "amazon.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amazon-to-sqlite",
        description="Save order history from Amazon.com to a SQLite database.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser(
        "import",
        help="Import CSV files (or directories of CSVs) from an Amazon "
        "'Request My Data' export into SQLite.",
    )
    import_parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="CSV files or directories containing CSV files",
    )
    import_parser.add_argument(
        "--db",
        default=DEFAULT_DB,
        help=f"SQLite database file (default: {DEFAULT_DB})",
    )
    import_parser.add_argument(
        "--replace",
        action="store_true",
        help="Drop existing destination tables before importing",
    )
    import_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )

    formats_parser = subparsers.add_parser(
        "check-formats",
        help="Check amazon.com for available formats (Kindle, audiobook, ...) "
        "of books. With no ASINs, checks every print book found in the "
        "database.",
    )
    formats_parser.add_argument(
        "asins",
        nargs="*",
        help="ASINs to check (default: print books from the database)",
    )
    formats_parser.add_argument(
        "--db",
        default=DEFAULT_DB,
        help=f"SQLite database file (default: {DEFAULT_DB})",
    )
    formats_parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait between Amazon requests (default: 1.0)",
    )
    return parser


def _connect(db_file: str) -> Connection:
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def _import_command(args: argparse.Namespace) -> int:
    csv_paths = expand_paths(args.paths)
    if not csv_paths:
        print("No CSV files found.", file=sys.stderr)
        return 1

    conn = _connect(args.db)
    dropped: set[str] = set()
    exit_code = 0
    try:
        for csv_path in csv_paths:
            if not csv_path.exists():
                print(f"{csv_path}: file not found", file=sys.stderr)
                exit_code = 1
                continue
            try:
                exit_code = max(
                    exit_code,
                    _import_one(conn, csv_path, args, dropped),
                )
            except (
                csv.Error,
                EmptyCsvError,
                HeaderMismatchError,
                OSError,
                sqlite3.Error,
            ) as exc:
                print(f"{csv_path}: {exc}", file=sys.stderr)
                exit_code = 1
    finally:
        conn.close()
    return exit_code


def _import_one(
    conn: Connection,
    csv_path: Path,
    args: argparse.Namespace,
    dropped: set[str],
) -> int:
    table = peek_table_name(csv_path)
    if args.replace and table not in dropped:
        db.drop_table(conn, table)
        dropped.add(table)

    bar = tqdm(desc=csv_path.name, unit=" rows") if not args.quiet else None
    try:
        with conn:
            result = import_file(
                conn,
                csv_path,
                progress=bar.update if bar is not None else None,
            )
    finally:
        if bar is not None:
            bar.close()

    if not args.quiet:
        print(
            f"{csv_path.name}: {result.rows_inserted} new rows in "
            f"'{result.table}' ({result.rows_skipped} duplicates skipped)",
        )
        if result.extra_columns:
            print(
                f"  note: ignored unrecognized column(s): "
                f"{', '.join(result.extra_columns)}",
            )
    return 0


def _check_formats_command(args: argparse.Namespace) -> int:
    if args.delay < 0:
        print("--delay must be non-negative", file=sys.stderr)
        return 1

    if args.asins:
        books = [{"asin": asin, "title": ""} for asin in args.asins]
    else:
        if not Path(args.db).exists():
            print(
                f"Database {args.db!r} not found. Run the import command first "
                "or pass ASINs explicitly.",
                file=sys.stderr,
            )
            return 1
        conn = _connect(args.db)
        try:
            books = db.get_books(conn)
        except sqlite3.Error as exc:
            print(f"{args.db}: {exc}", file=sys.stderr)
            return 1
        finally:
            conn.close()
        if not books:
            print("No print books (ISBN-10 ASINs) found in the database.")
            return 0

    for position, book in enumerate(books):
        if book["title"]:
            print(f"\n{book['title']} ({book['asin']})")
        else:
            print(f"\n{book['asin']}")
        check_book_formats(book["asin"])
        if args.delay > 0 and position < len(books) - 1:
            time.sleep(args.delay)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "import":
        return _import_command(args)
    if args.command == "check-formats":
        return _check_formats_command(args)
    return 1  # pragma: no cover - unreachable, subparsers are required


if __name__ == "__main__":
    sys.exit(main())
