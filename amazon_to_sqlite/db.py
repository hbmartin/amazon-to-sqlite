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


def sanitize_name(name: str) -> str:
    """Turn an arbitrary string into a safe SQLite identifier."""
    safe = "".join(
        c if c.isalnum() or c == "_" else "_" for c in name.replace(" ", "_")
    )
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe or safe[0].isdigit():
        safe = f"t_{safe}"
    return safe


FIELDS = [sanitize_name(field) for field in FIELD_TYPES]

INDEXED_FIELDS = ("Order_Date", "ASIN", "Order_Status")


def create_table_statement() -> str:
    typed_fields = [
        f'"{sanitize_name(field)}" {data_type}'
        for field, data_type in FIELD_TYPES.items()
    ]
    fields_str = ",\n    ".join(typed_fields)
    return f"CREATE TABLE IF NOT EXISTS {TABLE_NAME} ({fields_str});"


def _unique_index_statement(table: str, columns: list[str]) -> str:
    # NULLs compare as distinct in SQLite unique indexes, so index over
    # COALESCE(column, '') to make rows containing NULLs deduplicate too.
    exprs = ", ".join(f"COALESCE(\"{column}\", '')" for column in columns)
    return (
        f'CREATE UNIQUE INDEX IF NOT EXISTS "idx_{table}_unique" '
        f'ON "{table}" ({exprs});'
    )


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
    conn.execute(_unique_index_statement(TABLE_NAME, FIELDS))
    for field in INDEXED_FIELDS:
        conn.execute(
            f'CREATE INDEX IF NOT EXISTS "idx_{TABLE_NAME}_{field}" '
            f'ON "{TABLE_NAME}" ("{field}");',
        )
    _create_fts(conn)
    conn.commit()


def create_generic_table(conn: Connection, table: str, columns: list[str]) -> None:
    cols = ",\n    ".join(f'"{column}" TEXT' for column in columns)
    conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({cols});')
    conn.execute(_unique_index_statement(table, columns))
    conn.commit()


def drop_table(conn: Connection, table: str) -> None:
    conn.execute(f'DROP TABLE IF EXISTS "{table}";')
    if table == TABLE_NAME:
        conn.execute(f'DROP TABLE IF EXISTS "{FTS_TABLE_NAME}";')
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
    insert_query = f'INSERT OR IGNORE INTO "{table}" VALUES ({placeholders})'  # noqa: S608
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
        f'SELECT DISTINCT "ASIN", "Product_Name" FROM "{TABLE_NAME}" '  # noqa: S608
        'WHERE "ASIN" IS NOT NULL AND "ASIN" != \'\';',
    )
    return [
        {"asin": asin, "title": title or ""}
        for asin, title in cursor.fetchall()
        if is_isbn10(asin)
    ]
