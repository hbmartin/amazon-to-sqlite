import sqlite3
from pathlib import Path

import pytest

from amazon_to_sqlite import __version__, db
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
    main(["import", "--quiet", str(orders_csv), "--db", str(db_file)])
    main(["import", "--quiet", "--replace", str(orders_csv), "--db", str(db_file)])
    conn = sqlite3.connect(db_file)
    count = conn.execute(f"SELECT COUNT(*) FROM {db.TABLE_NAME}").fetchone()[0]
    conn.close()
    assert count == 2


def test_import_missing_file(tmp_path: Path, capsys):
    db_file = tmp_path / "amazon.db"
    code = main(["import", str(tmp_path / "nope.csv"), "--db", str(db_file)])
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_import_bad_headers(tmp_path: Path, capsys):
    bad = tmp_path / "bad.csv"
    bad.write_text("", encoding="utf-8")
    db_file = tmp_path / "amazon.db"
    code = main(["import", str(bad), "--db", str(db_file)])
    assert code == 1
    assert "empty" in capsys.readouterr().err


def test_check_formats_missing_db(tmp_path: Path, capsys):
    code = main(["check-formats", "--db", str(tmp_path / "missing.db")])
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_check_formats_no_books(tmp_path: Path, orders_csv: Path, capsys, monkeypatch):
    db_file = tmp_path / "amazon.db"
    calls: list[str] = []
    monkeypatch.setattr(
        "amazon_to_sqlite.__main__.check_book_formats",
        calls.append,
    )
    main(["import", "--quiet", str(orders_csv), "--db", str(db_file)])
    capsys.readouterr()
    assert main(["check-formats", "--db", str(db_file)]) == 0
    assert calls == ["0306406152"]


def test_check_formats_explicit_asins(monkeypatch, capsys):
    calls: list[str] = []
    monkeypatch.setattr(
        "amazon_to_sqlite.__main__.check_book_formats",
        calls.append,
    )
    assert main(["check-formats", "0306406152", "080442957X"]) == 0
    assert calls == ["0306406152", "080442957X"]
    assert "0306406152" in capsys.readouterr().out
