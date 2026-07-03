import sqlite3

from amazon_to_sqlite import db


def test_create_table_statement_sanitizes_names():
    statement = db.create_table_statement()
    assert '"Carrier_Name_Tracking_Number" TEXT' in statement
    assert "&" not in statement


def test_sanitize_name():
    assert db.sanitize_name("Carrier Name & Tracking Number") == (
        "Carrier_Name_Tracking_Number"
    )
    assert db.sanitize_name("Order ID") == "Order_ID"
    assert db.sanitize_name("123 Fun") == "t_123_Fun"


def test_create_table_is_idempotent(conn: sqlite3.Connection):
    db.create_table(conn)
    db.create_table(conn)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert db.TABLE_NAME in tables


def test_create_table_adds_indexes_and_fts(conn: sqlite3.Connection):
    db.create_table(conn)
    indexes = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    assert f"idx_{db.TABLE_NAME}_unique" in indexes
    assert f"idx_{db.TABLE_NAME}_Order_Date" in indexes
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert db.FTS_TABLE_NAME in tables


def test_noneify():
    assert db.noneify(["a", "Not Applicable", "Not Available", ""]) == [
        "a",
        None,
        None,
        "",
    ]


def test_insert_deduplicates(conn: sqlite3.Connection):
    db.create_table(conn)
    row = ["x"] * len(db.FIELDS)
    assert db.insert(conn, [row, row]) == 1
    assert db.insert(conn, [row]) == 0
    count = conn.execute(f"SELECT COUNT(*) FROM {db.TABLE_NAME}").fetchone()[0]
    assert count == 1


def test_insert_deduplicates_rows_with_nulls(conn: sqlite3.Connection):
    db.create_table(conn)
    row = ["Not Applicable"] * len(db.FIELDS)
    db.insert(conn, [row])
    assert db.insert(conn, [row]) == 0


def test_fts_search(conn: sqlite3.Connection):
    db.create_table(conn)
    row = ["x"] * len(db.FIELDS)
    row[db.FIELDS.index("Product_Name")] = "The Pragmatic Programmer"
    db.insert(conn, [row])
    hits = conn.execute(
        f"SELECT Product_Name FROM {db.FTS_TABLE_NAME} "
        f"WHERE {db.FTS_TABLE_NAME} MATCH 'pragmatic'",
    ).fetchall()
    assert hits == [("The Pragmatic Programmer",)]


def test_is_isbn10():
    assert db.is_isbn10("0306406152")
    assert db.is_isbn10("080442957X")
    assert not db.is_isbn10("0306406153")  # bad checksum
    assert not db.is_isbn10("B08N5WRWNW")  # regular ASIN
    assert not db.is_isbn10("030640615")  # too short
    assert not db.is_isbn10("03064061521")  # too long


def test_get_books(conn: sqlite3.Connection):
    db.create_table(conn)
    book_row = ["x"] * len(db.FIELDS)
    book_row[db.FIELDS.index("ASIN")] = "0306406152"
    book_row[db.FIELDS.index("Product_Name")] = "A Book"
    gadget_row = ["y"] * len(db.FIELDS)
    gadget_row[db.FIELDS.index("ASIN")] = "B08N5WRWNW"
    db.insert(conn, [book_row, gadget_row])
    assert db.get_books(conn) == [{"asin": "0306406152", "title": "A Book"}]


def test_drop_table(conn: sqlite3.Connection):
    db.create_table(conn)
    db.drop_table(conn, db.TABLE_NAME)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert db.TABLE_NAME not in tables
    assert db.FTS_TABLE_NAME not in tables
