import sqlite3
from pathlib import Path

import pytest
from conftest import HEADERS, make_row, write_csv

from amazon_to_sqlite import db, importer


def test_validate_headers_passthrough():
    indexes, extras = importer.validate_headers(HEADERS)
    assert indexes == list(range(len(HEADERS)))
    assert extras == []


def test_validate_headers_reordered():
    reordered = list(reversed(HEADERS))
    indexes, _ = importer.validate_headers(reordered)
    assert [reordered[i] for i in indexes] == HEADERS


def test_validate_headers_missing():
    with pytest.raises(importer.HeaderMismatchError) as excinfo:
        importer.validate_headers(HEADERS[:-2])
    assert excinfo.value.missing == HEADERS[-2:]


def test_validate_headers_extra_columns():
    _, extras = importer.validate_headers([*HEADERS, "New Amazon Column"])
    assert extras == ["New Amazon Column"]


def test_make_row_rejects_unknown_override():
    with pytest.raises(ValueError, match="Unknown order-history field"):
        make_row(**{"Order Id": "typo"})


def test_normalize_date():
    assert importer.normalize_date("2023-08-12T20:23:53Z") == (
        "2023-08-12T20:23:53+00:00"
    )
    assert importer.normalize_date("08/12/2023") == "2023-08-12T00:00:00"
    assert importer.normalize_date("8/2/2023 14:30:00") == "2023-08-02T14:30:00"
    assert importer.normalize_date("not a date") == "not a date"
    assert importer.normalize_date("  not a date  ") == "not a date"
    assert importer.normalize_date("") is None
    assert importer.normalize_date("   ") is None


def test_parse_money():
    assert importer.parse_money("$1,234.56") == 1234.56
    assert importer.parse_money("USD 12.99") == 12.99
    assert importer.parse_money("-3.50") == -3.50
    assert importer.parse_money("($1.99)") == -1.99
    assert importer.parse_money("free") == "free"
    assert importer.parse_money("") is None
    assert importer.parse_money("   ") is None


def test_parse_int():
    assert importer.parse_int("2") == 2
    assert importer.parse_int("2.0") == 2
    assert importer.parse_int("many") == "many"
    assert importer.parse_int("Infinity") == "Infinity"
    assert importer.parse_int("") is None
    assert importer.parse_int("   ") is None


def test_import_order_history(conn: sqlite3.Connection, orders_csv: Path):
    result = importer.import_file(conn, orders_csv)
    assert result.table == db.TABLE_NAME
    assert result.rows_read == 2
    assert result.rows_inserted == 2
    rows = conn.execute(
        "SELECT Order_Date, Unit_Price, Quantity, Gift_Message "
        f"FROM {db.TABLE_NAME} ORDER BY Order_Date",
    ).fetchall()
    assert rows[0] == ("2023-08-12T20:23:53+00:00", 12.99, 1, None)


def test_reimport_is_idempotent(conn: sqlite3.Connection, orders_csv: Path):
    importer.import_file(conn, orders_csv)
    result = importer.import_file(conn, orders_csv)
    assert result.rows_read == 2
    assert result.rows_inserted == 0
    assert result.rows_skipped == 2
    count = conn.execute(f"SELECT COUNT(*) FROM {db.TABLE_NAME}").fetchone()[0]
    assert count == 2


def test_import_with_reordered_and_extra_columns(
    conn: sqlite3.Connection,
    tmp_path: Path,
):
    headers = ["Mystery Column", *reversed(HEADERS)]
    row = make_row()
    shuffled = ["mystery", *reversed(row)]
    csv_path = write_csv(tmp_path / "reordered.csv", [shuffled], headers=headers)
    result = importer.import_file(conn, csv_path)
    assert result.table == db.TABLE_NAME
    assert result.extra_columns == ["Mystery Column"]
    stored = conn.execute(
        f"SELECT Order_ID, Product_Name FROM {db.TABLE_NAME}",
    ).fetchone()
    assert stored == ("111-2223334-5556667", "An Example Book")


def test_import_generic_csv(conn: sqlite3.Connection, tmp_path: Path):
    csv_path = tmp_path / "Digital Items.csv"
    csv_path.write_text(
        "Title,OrderId\nSome Ebook,D01-123\nOther Ebook,D01-456\n",
        encoding="utf-8",
    )
    result = importer.import_file(conn, csv_path)
    assert result.table == "digital_items"
    assert result.rows_inserted == 2
    # Re-import deduplicates generic tables too
    again = importer.import_file(conn, csv_path)
    assert again.rows_inserted == 0


def test_import_generic_case_insensitive_duplicate_headers(
    conn: sqlite3.Connection,
    tmp_path: Path,
):
    csv_path = tmp_path / "Case Headers.csv"
    csv_path.write_text("Title,title\nSome Ebook,D01-123\n", encoding="utf-8")
    result = importer.import_file(conn, csv_path)
    assert result.rows_inserted == 1
    columns = [
        row[1] for row in conn.execute(f"PRAGMA table_info({result.table})").fetchall()
    ]
    assert columns == ["Title", "title_2"]


def test_short_rows_are_padded(conn: sqlite3.Connection, tmp_path: Path):
    row = make_row()[:-3]  # drop trailing columns
    csv_path = write_csv(tmp_path / "short.csv", [row])
    result = importer.import_file(conn, csv_path)
    assert result.rows_inserted == 1


def test_empty_csv_raises(conn: sqlite3.Connection, tmp_path: Path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(importer.EmptyCsvError):
        importer.import_file(conn, empty)

    empty_header = tmp_path / "empty-header.csv"
    empty_header.write_text("\r", encoding="utf-8")
    with pytest.raises(importer.EmptyCsvError):
        importer.import_file(conn, empty_header)


def test_expand_paths(tmp_path: Path, orders_csv: Path):
    nested = tmp_path / "nested"
    nested.mkdir()
    upper = nested / "A.CSV"
    upper.write_text("A,B\n3,4\n", encoding="utf-8")
    other = nested / "b.csv"
    other.write_text("A,B\n1,2\n", encoding="utf-8")
    assert importer.expand_paths([tmp_path]) == [orders_csv, upper, other]
    assert importer.expand_paths([orders_csv]) == [orders_csv]


def test_peek_table_name(orders_csv: Path, tmp_path: Path):
    assert importer.peek_table_name(orders_csv) == db.TABLE_NAME
    other = tmp_path / "Digital Orders.csv"
    other.write_text("A,B\n", encoding="utf-8")
    assert importer.peek_table_name(other) == "digital_orders"


def test_progress_callback(conn: sqlite3.Connection, orders_csv: Path):
    seen: list[int] = []
    importer.import_file(conn, orders_csv, progress=seen.append)
    assert sum(seen) == 2
