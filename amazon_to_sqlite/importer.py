"""CSV import logic: header validation, normalization and bulk loading."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from amazon_to_sqlite import db

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from pathlib import Path
    from sqlite3 import Connection

DEFAULT_CHUNK_SIZE = 1000

DATE_FIELDS = frozenset({"Order Date", "Ship Date"})
MONEY_FIELDS = frozenset(
    {
        "Unit Price",
        "Unit Price Tax",
        "Shipping Charge",
        "Total Discounts",
        "Total Owed",
        "Shipment Item Subtotal",
        "Shipment Item Subtotal Tax",
    },
)
INT_FIELDS = frozenset({"Quantity"})

_DATE_FORMATS = (
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%m/%d/%y",
)

_NON_NUMERIC = re.compile(r"[^0-9.\-]")


class HeaderMismatchError(ValueError):
    """Raised when a CSV's headers do not match the expected schema."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(
            "CSV is missing expected column(s): " + ", ".join(missing),
        )


class EmptyCsvError(ValueError):
    """Raised when a CSV file has no header row."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path} is empty (no header row)")


@dataclass
class ImportResult:
    path: Path
    table: str
    rows_read: int = 0
    rows_inserted: int = 0
    extra_columns: list[str] = field(default_factory=list)

    @property
    def rows_skipped(self) -> int:
        """Rows read but not inserted (duplicates ignored by the unique index)."""
        return self.rows_read - self.rows_inserted


def validate_headers(headers: list[str]) -> tuple[list[int], list[str]]:
    """Map expected order-history fields to CSV column indexes by name.

    Returns (index of each expected field in the CSV, extra column names).
    Raises HeaderMismatchError if any expected column is absent.
    """
    stripped = [h.strip() for h in headers]
    missing = [f for f in db.FIELD_TYPES if f not in stripped]
    if missing:
        raise HeaderMismatchError(missing)
    indexes = [stripped.index(f) for f in db.FIELD_TYPES]
    extras = [h for h in stripped if h not in db.FIELD_TYPES]
    return indexes, extras


def is_order_history(headers: list[str]) -> bool:
    stripped = {h.strip() for h in headers}
    return all(f in stripped for f in db.FIELD_TYPES)


def _looks_like_order_history_file(csv_path: Path) -> bool:
    return csv_path.name.lower().startswith("retail.orderhistory")


def normalize_date(value: str) -> str | None:
    """Normalize a date string to ISO 8601; return it unchanged if unparseable."""
    text = value.strip()
    if not text:
        return None
    iso_candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(iso_candidate).isoformat()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).isoformat()  # noqa: DTZ007
        except ValueError:
            continue
    return text


def parse_money(value: str) -> float | str | None:
    """Parse a currency amount ("$1,234.56", "USD 12.99") to a float.

    Amounts are stored as REAL (floats): convenient for SUM()/ROUND() in
    queries, at the cost of binary-float representation of cents.
    Returns None if empty, or the original string if it cannot be parsed.
    """
    text = value.strip()
    if not text:
        return None
    cleaned = _NON_NUMERIC.sub("", text)
    if not cleaned:
        return value
    if text.startswith("(") and text.endswith(")") and not cleaned.startswith("-"):
        cleaned = f"-{cleaned}"
    try:
        return float(cleaned)
    except ValueError:
        return value


def parse_int(value: str) -> int | str | None:
    if not value.strip():
        return None
    try:
        return int(float(value))
    except (OverflowError, ValueError):
        return value


def _converters() -> list[Callable[[str], str | float | int | None]]:
    converters: list[Callable[[str], str | float | int | None]] = []
    for original_name in db.FIELD_TYPES:
        if original_name in DATE_FIELDS:
            converters.append(normalize_date)
        elif original_name in MONEY_FIELDS:
            converters.append(parse_money)
        elif original_name in INT_FIELDS:
            converters.append(parse_int)
        else:
            converters.append(lambda value: value)
    return converters


def table_name_for(path: Path) -> str:
    return db.sanitize_name(path.stem).lower()


def peek_table_name(csv_path: Path) -> str:
    """Determine the destination table without importing anything."""
    headers = _read_headers(csv_path)
    if is_order_history(headers) or _looks_like_order_history_file(csv_path):
        return db.TABLE_NAME
    return table_name_for(csv_path)


def _read_headers(csv_path: Path) -> list[str]:
    with csv_path.open(newline="", encoding="utf-8-sig") as csvfile:
        headers = next(csv.reader(csvfile, quotechar='"'), None)
    if not headers:
        raise EmptyCsvError(csv_path)
    return headers


def expand_paths(paths: Iterable[Path]) -> list[Path]:
    """Expand files and directories into a sorted list of CSV files."""
    expanded: list[Path] = []
    for path in paths:
        if path.is_dir():
            expanded.extend(
                sorted(
                    candidate
                    for candidate in path.rglob("*")
                    if candidate.is_file() and candidate.suffix.lower() == ".csv"
                ),
            )
        else:
            expanded.append(path)
    return expanded


def _chunks(
    reader: Iterator[list[str]],
    chunk_size: int,
) -> Iterator[list[list[str]]]:
    chunk: list[list[str]] = []
    for row in reader:
        chunk.append(row)
        if len(chunk) == chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _normalize_order_row(
    row: list[str],
    indexes: list[int],
    converters: list[Callable[[str], str | float | int | None]],
    header_count: int,
) -> list[str | float | int | None]:
    padded = row + [""] * (header_count - len(row))
    reordered = db.noneify([padded[i] for i in indexes])
    return [
        converters[position](value) if value is not None else None
        for position, value in enumerate(reordered)
    ]


def import_order_history(
    conn: Connection,
    csv_path: Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    progress: Callable[[int], object] | None = None,
) -> ImportResult:
    """Load an Amazon order-history CSV into the amazon_orders table."""
    db.create_table(conn)
    result = ImportResult(path=csv_path, table=db.TABLE_NAME)
    converters = _converters()

    with csv_path.open(newline="", encoding="utf-8-sig") as csvfile:
        reader = csv.reader(csvfile, quotechar='"')
        headers = next(reader, None)
        if not headers:
            raise EmptyCsvError(csv_path)
        indexes, extras = validate_headers(headers)
        result.extra_columns = extras

        for chunk in _chunks(reader, chunk_size):
            rows = [
                _normalize_order_row(row, indexes, converters, len(headers))
                for row in chunk
            ]
            result.rows_inserted += db.insert_rows(
                conn,
                db.TABLE_NAME,
                rows,
                len(db.FIELDS),
            )
            result.rows_read += len(chunk)
            if progress is not None:
                progress(len(chunk))

    conn.commit()
    return result


def import_generic(
    conn: Connection,
    csv_path: Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    progress: Callable[[int], object] | None = None,
) -> ImportResult:
    """Load any other CSV from the Amazon export into its own TEXT table."""
    table = table_name_for(csv_path)
    result = ImportResult(path=csv_path, table=table)

    with csv_path.open(newline="", encoding="utf-8-sig") as csvfile:
        reader = csv.reader(csvfile, quotechar='"')
        headers = next(reader, None)
        if not headers:
            raise EmptyCsvError(csv_path)
        columns = _unique_columns(headers)
        db.create_generic_table(conn, table, columns)

        for chunk in _chunks(reader, chunk_size):
            rows: list[list[str | float | None]] = [
                list(
                    db.noneify(
                        (row + [""] * (len(columns) - len(row)))[: len(columns)],
                    ),
                )
                for row in chunk
            ]
            result.rows_inserted += db.insert_rows(conn, table, rows, len(columns))
            result.rows_read += len(chunk)
            if progress is not None:
                progress(len(chunk))

    conn.commit()
    return result


def _unique_columns(headers: list[str]) -> list[str]:
    columns: list[str] = []
    lower_columns: set[str] = set()
    for position, header in enumerate(headers):
        base = db.sanitize_name(header.strip()) if header.strip() else f"col_{position}"
        name = base
        suffix = 2
        while name.lower() in lower_columns:
            name = f"{base}_{suffix}"
            suffix += 1
        columns.append(name)
        lower_columns.add(name.lower())
    return columns


def import_file(
    conn: Connection,
    csv_path: Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    progress: Callable[[int], object] | None = None,
) -> ImportResult:
    """Import a CSV, routing order history and other exports appropriately."""
    headers = _read_headers(csv_path)
    if is_order_history(headers) or _looks_like_order_history_file(csv_path):
        return import_order_history(
            conn,
            csv_path,
            chunk_size=chunk_size,
            progress=progress,
        )
    return import_generic(conn, csv_path, chunk_size=chunk_size, progress=progress)
