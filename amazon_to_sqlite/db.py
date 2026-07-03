"""SQLite schema management and low-level insert helpers."""

import re
import sqlite3
from collections.abc import Iterable, Sequence
from sqlite3 import Connection

FIELD_TYPES: dict[str, str] = {
    "Website": "TEXT",
    "Order ID": "TEXT",
    "Order Date": "TEXT",
    "Purchase Order Number": "TEXT",
    "Currency": "TEXT",
    "Unit Price": "REAL",
    "Unit Price Tax": "REAL",
    "Shipping Charge": "REAL",
    "Total Discounts": "REAL",
    "Total Owed": "REAL",
    "Shipment Item Subtotal": "REAL",
    "Shipment Item Subtotal Tax": "REAL",
    "ASIN": "TEXT",
    "Product Condition": "TEXT",
    "Quantity": "INTEGER",
    "Payment Instrument Type": "TEXT",
    "Order Status": "TEXT",
    "Shipment Status": "TEXT",
    "Ship Date": "TEXT",
    "Shipping Option": "TEXT",
    "Shipping Address": "TEXT",
    "Billing Address": "TEXT",
    "Carrier Name & Tracking Number": "TEXT",
    "Product Name": "TEXT",
    "Gift Message": "TEXT",
    "Gift Sender Name": "TEXT",
    "Gift Recipient Contact Details": "TEXT",
    "Item Serial Number": "TEXT",
}

TABLE_NAME = "amazon_orders"
FTS_TABLE_NAME = "amazon_orders_fts"

MISSING_VALUES = ("Not Applicable", "Not Available")

ISBN10_LENGTH = 10

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sanitize_name(name: str) -> str:
    """Turn an arbitrary string into a safe SQLite identifier."""
    safe = "".join(
        c if c.isascii() and (c.isalnum() or c == "_") else "_"
        for c in name.replace(" ", "_")
    )
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe or safe[0].isdigit():
        safe = f"t_{safe}"
    return safe


FIELDS = [sanitize_name(field) for field in FIELD_TYPES]

INDEXED_FIELDS = ("Order_Date", "ASIN", "Order_Status")


def _safe_identifier(name: str) -> str:
    safe = sanitize_name(name)
    if not _IDENTIFIER_RE.fullmatch(safe):
        msg = "Unsafe SQLite identifier"
        raise ValueError(msg)
    return safe


def _quoted_identifier(name: str) -> str:
    return f'"{_safe_identifier(name)}"'


def create_table_statement() -> str:
    typed_fields = [
        f'"{sanitize_name(field)}" {data_type}'
        for field, data_type in FIELD_TYPES.items()
    ]
    fields_str = ",\n    ".join(typed_fields)
    return f"CREATE TABLE IF NOT EXISTS {TABLE_NAME} ({fields_str});"


def _unique_index_name(table: str) -> str:
    safe_table = _safe_identifier(table)
    return f"idx_{safe_table}_unique"


def _unique_index_exists(conn: Connection, table: str) -> bool:
    index_name = _unique_index_name(table)
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
            (index_name,),
        ).fetchone()
        is not None
    )


def _unique_index_statement(table: str, columns: list[str]) -> str:
    safe_table = _safe_identifier(table)
    index_name = _unique_index_name(safe_table)
    # NULLs compare as distinct in SQLite unique indexes, so index over
    # COALESCE(column, '') to make rows containing NULLs deduplicate too.
    exprs = ", ".join(
        f"COALESCE({_quoted_identifier(column)}, '')" for column in columns
    )
    return (
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_quoted_identifier(index_name)} "
        f"ON {_quoted_identifier(safe_table)} ({exprs});"
    )


def _deduplicate_existing_rows(
    conn: Connection,
    table: str,
    columns: Sequence[str],
) -> None:
    safe_table = _safe_identifier(table)
    group_exprs = ", ".join(
        f"COALESCE({_quoted_identifier(column)}, '')" for column in columns
    )
    delete_query = (
        f"DELETE FROM {_quoted_identifier(safe_table)} "  # noqa: S608
        f"WHERE rowid NOT IN ("
        f"SELECT MIN(rowid) FROM {_quoted_identifier(safe_table)} "
        f"GROUP BY {group_exprs}"
        ");"
    )
    conn.execute(delete_query)


def _create_fts(conn: Connection) -> None:
    try:
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE_NAME} USING fts5("
            f"Product_Name, content='{TABLE_NAME}', content_rowid='rowid');",
        )
    except sqlite3.OperationalError:
        # FTS5 is compiled into virtually every modern SQLite, but degrade
        # gracefully on builds without it.
        return
    conn.execute(
        f"CREATE TRIGGER IF NOT EXISTS {TABLE_NAME}_ai "  # noqa: S608
        f"AFTER INSERT ON {TABLE_NAME} BEGIN "
        f"INSERT INTO {FTS_TABLE_NAME}(rowid, Product_Name) "
        f"VALUES (new.rowid, new.Product_Name); END;",
    )
    conn.execute(
        f"CREATE TRIGGER IF NOT EXISTS {TABLE_NAME}_ad "  # noqa: S608
        f"AFTER DELETE ON {TABLE_NAME} BEGIN "
        f"INSERT INTO {FTS_TABLE_NAME}({FTS_TABLE_NAME}, rowid, Product_Name) "
        f"VALUES ('delete', old.rowid, old.Product_Name); END;",
    )
    conn.execute(
        f"CREATE TRIGGER IF NOT EXISTS {TABLE_NAME}_au "  # noqa: S608
        f"AFTER UPDATE ON {TABLE_NAME} BEGIN "
        f"INSERT INTO {FTS_TABLE_NAME}({FTS_TABLE_NAME}, rowid, Product_Name) "
        f"VALUES ('delete', old.rowid, old.Product_Name); "
        f"INSERT INTO {FTS_TABLE_NAME}(rowid, Product_Name) "
        f"VALUES (new.rowid, new.Product_Name); END;",
    )


def create_table(conn: Connection) -> None:
    conn.execute(create_table_statement())
    if not _unique_index_exists(conn, TABLE_NAME):
        _deduplicate_existing_rows(conn, TABLE_NAME, FIELDS)
    conn.execute(_unique_index_statement(TABLE_NAME, FIELDS))
    for field in INDEXED_FIELDS:
        conn.execute(
            f'CREATE INDEX IF NOT EXISTS "idx_{TABLE_NAME}_{field}" '
            f'ON "{TABLE_NAME}" ("{field}");',
        )
    _create_fts(conn)
    conn.commit()


def create_generic_table(conn: Connection, table: str, columns: list[str]) -> None:
    safe_table = _safe_identifier(table)
    safe_columns = [_safe_identifier(column) for column in columns]
    cols = ",\n    ".join(
        f"{_quoted_identifier(column)} TEXT" for column in safe_columns
    )
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {_quoted_identifier(safe_table)} ({cols});",
    )
    if not _unique_index_exists(conn, safe_table):
        _deduplicate_existing_rows(conn, safe_table, safe_columns)
    conn.execute(_unique_index_statement(safe_table, safe_columns))
    conn.commit()


def drop_table(conn: Connection, table: str) -> None:
    safe_table = _safe_identifier(table)
    conn.execute(f"DROP TABLE IF EXISTS {_quoted_identifier(safe_table)};")
    if safe_table == TABLE_NAME:
        conn.execute(f"DROP TABLE IF EXISTS {_quoted_identifier(FTS_TABLE_NAME)};")
    conn.commit()


def noneify(data: list[str]) -> list[str | None]:
    return [d if d not in MISSING_VALUES else None for d in data]


def insert_rows(
    conn: Connection,
    table: str,
    rows: Iterable[Sequence[str | float | int | None]],
    column_count: int,
) -> int:
    """Insert rows with INSERT OR IGNORE and return how many were new."""
    placeholders = ", ".join(["?"] * column_count)
    insert_query = (
        f"INSERT OR IGNORE INTO {_quoted_identifier(table)} "  # noqa: S608
        f"VALUES ({placeholders})"
    )
    cursor = conn.executemany(insert_query, rows)
    # rowcount counts only the statement's direct changes, unlike
    # Connection.total_changes which also counts FTS trigger writes.
    return cursor.rowcount


def insert(conn: Connection, rows: list[list[str]]) -> int:
    """Insert raw order-history rows (already ordered to match FIELDS)."""
    inserted = insert_rows(
        conn,
        TABLE_NAME,
        [list(noneify(row)) for row in rows],
        len(FIELDS),
    )
    conn.commit()
    return inserted


def is_isbn10(value: str) -> bool:
    """Check whether an ASIN is a valid ISBN-10 (i.e. a print book)."""
    if len(value) != ISBN10_LENGTH or not value[:9].isdigit():
        return False
    check = value[9]
    if not (check.isdigit() or check in "Xx"):
        return False
    total = sum((10 - i) * int(digit) for i, digit in enumerate(value[:9]))
    total += 10 if check in "Xx" else int(check)
    return total % 11 == 0


def get_books(conn: Connection) -> list[dict[str, str]]:
    """Return distinct ISBN-10 ASINs (print books) with their product names."""
    cursor = conn.execute(
        f"SELECT \"ASIN\", COALESCE(MAX(NULLIF(\"Product_Name\", '')), '') "  # noqa: S608
        f"FROM {_quoted_identifier(TABLE_NAME)} "
        'WHERE "ASIN" IS NOT NULL AND "ASIN" != \'\' '
        'GROUP BY "ASIN" '
        'ORDER BY "ASIN";',
    )
    return [
        {"asin": asin, "title": title or ""}
        for asin, title in cursor.fetchall()
        if is_isbn10(asin)
    ]
