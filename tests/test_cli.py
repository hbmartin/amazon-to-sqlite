import csv
import sqlite3
from pathlib import Path

import pytest
from conftest import make_row, write_csv

from amazon_to_sqlite import __version__, db, importer
from amazon_to_sqlite.__main__ import main


def test_no_arguments_shows_usage(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
    assert "usage:" in capsys.readouterr().err.lower()


def test_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_import_command(tmp_path: Path, orders_csv: Path, capsys):
    db_file = tmp_path / "amazon.db"
    assert main(["import", str(orders_csv), "--db", str(db_file)]) == 0
    output = capsys.readouterr().out
    assert "2 new rows" in output
    conn = sqlite3.connect(db_file)
    count = conn.execute(f"SELECT COUNT(*) FROM {db.TABLE_NAME}").fetchone()[0]
    conn.close()
    assert count == 2


def test_import_quiet(tmp_path: Path, orders_csv: Path, capsys):
    db_file = tmp_path / "amazon.db"
    assert main(["import", "--quiet", str(orders_csv), "--db", str(db_file)]) == 0
    assert capsys.readouterr().out == ""


def test_import_directory(tmp_path: Path, orders_csv: Path):
    db_file = tmp_path / "amazon.db"
    generic = tmp_path / "Digital Items.csv"
    generic.write_text("Title,OrderId\nEbook,D01-123\n", encoding="utf-8")
    assert main(["import", "--quiet", str(tmp_path), "--db", str(db_file)]) == 0
    conn = sqlite3.connect(db_file)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    assert db.TABLE_NAME in tables
    assert "digital_items" in tables


def test_import_replace(tmp_path: Path, orders_csv: Path):
    db_file = tmp_path / "amazon.db"
    assert main(["import", "--quiet", str(orders_csv), "--db", str(db_file)]) == 0
    assert (
        main(["import", "--quiet", "--replace", str(orders_csv), "--db", str(db_file)])
        == 0
    )
    conn = sqlite3.connect(db_file)
    count = conn.execute(f"SELECT COUNT(*) FROM {db.TABLE_NAME}").fetchone()[0]
    conn.close()
    assert count == 2


def test_import_missing_file(tmp_path: Path, capsys):
    db_file = tmp_path / "amazon.db"
    code = main(["import", str(tmp_path / "nope.csv"), "--db", str(db_file)])
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_import_empty_csv(tmp_path: Path, capsys):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    db_file = tmp_path / "amazon.db"
    code = main(["import", str(empty), "--db", str(db_file)])
    assert code == 1
    assert "empty" in capsys.readouterr().err


def test_import_bad_headers(tmp_path: Path, capsys):
    bad = tmp_path / "Retail.OrderHistory.Bad.csv"
    bad.write_text(
        "Website,Order ID\nAmazon.com,111-2223334-5556667\n", encoding="utf-8"
    )
    db_file = tmp_path / "amazon.db"
    code = main(["import", str(bad), "--db", str(db_file)])
    assert code == 1
    assert "missing expected column" in capsys.readouterr().err


def test_import_rolls_back_failed_file(
    tmp_path: Path,
    orders_csv: Path,
    capsys,
    monkeypatch,
):
    bad = write_csv(
        tmp_path / "bad.csv",
        [make_row(**{"Order ID": "111-9999999-9999999"})],
    )
    db_file = tmp_path / "amazon.db"
    real_import_file = importer.import_file

    def fail_after_partial_insert(conn, csv_path, *, chunk_size=1000, progress=None):
        if csv_path == bad:
            db.create_table(conn)
            partial_row = make_row(**{"Order ID": "111-9999999-9999999"})
            db.insert_rows(conn, db.TABLE_NAME, [partial_row], len(db.FIELDS))
            message = "malformed CSV"
            raise csv.Error(message)
        return real_import_file(
            conn,
            csv_path,
            chunk_size=chunk_size,
            progress=progress,
        )

    monkeypatch.setattr(
        "amazon_to_sqlite.__main__.import_file",
        fail_after_partial_insert,
    )
    code = main(["import", "--quiet", str(bad), str(orders_csv), "--db", str(db_file)])
    assert code == 1
    assert "malformed CSV" in capsys.readouterr().err
    conn = sqlite3.connect(db_file)
    count = conn.execute(f"SELECT COUNT(*) FROM {db.TABLE_NAME}").fetchone()[0]
    partial_count = conn.execute(
        f"SELECT COUNT(*) FROM {db.TABLE_NAME} WHERE Order_ID = ?",
        ("111-9999999-9999999",),
    ).fetchone()[0]
    conn.close()
    assert count == 2
    assert partial_count == 0


def test_check_formats_missing_db(tmp_path: Path, capsys):
    code = main(["check-formats", "--db", str(tmp_path / "missing.db")])
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_check_formats_bad_schema(tmp_path: Path, capsys):
    db_file = tmp_path / "missing-table.db"
    sqlite3.connect(db_file).close()
    code = main(["check-formats", "--db", str(db_file)])
    assert code == 1
    assert "no such table" in capsys.readouterr().err


def test_check_formats_from_db(tmp_path: Path, orders_csv: Path, capsys, monkeypatch):
    db_file = tmp_path / "amazon.db"
    calls: list[str] = []
    monkeypatch.setattr(
        "amazon_to_sqlite.__main__.check_book_formats",
        calls.append,
    )
    assert main(["import", "--quiet", str(orders_csv), "--db", str(db_file)]) == 0
    capsys.readouterr()
    assert main(["check-formats", "--db", str(db_file), "--delay", "0"]) == 0
    assert calls == ["0306406152"]


def test_check_formats_no_books(tmp_path: Path, capsys, monkeypatch):
    db_file = tmp_path / "amazon.db"
    no_book_csv = write_csv(
        tmp_path / "orders.csv",
        [make_row(**{"ASIN": "B08N5WRWNW", "Product Name": "Echo Dot"})],
    )
    calls: list[str] = []
    monkeypatch.setattr(
        "amazon_to_sqlite.__main__.check_book_formats",
        calls.append,
    )
    assert main(["import", "--quiet", str(no_book_csv), "--db", str(db_file)]) == 0
    capsys.readouterr()
    assert main(["check-formats", "--db", str(db_file), "--delay", "0"]) == 0
    assert calls == []
    assert "No print books" in capsys.readouterr().out


def test_check_formats_explicit_asins(monkeypatch, capsys):
    calls: list[str] = []
    monkeypatch.setattr(
        "amazon_to_sqlite.__main__.check_book_formats",
        calls.append,
    )
    assert main(["check-formats", "--delay", "0", "0306406152", "080442957X"]) == 0
    assert calls == ["0306406152", "080442957X"]
    assert "0306406152" in capsys.readouterr().out
