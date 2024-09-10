import csv
import sqlite3
import sys
from pathlib import Path
from sqlite3 import Connection

from amazon_to_sqlite.db import create_table, insert


def load_csv_to_sqlite(
    csv_file: str,
    db_file: str,
    chunk_size: int = 1000,
) -> None:
    conn: Connection = sqlite3.connect(db_file)
    create_table(conn)

    with Path(csv_file).open(newline="", encoding="utf-8-sig") as csvfile:
        csv_reader = csv.reader(csvfile, quotechar='"')
        headers = next(csv_reader)
        print(headers)

        chunk = []
        total_rows = 0
        for row in csv_reader:
            chunk.append(row)
            if len(chunk) == chunk_size:
                insert(conn, chunk)
                total_rows += len(chunk)
                print(f"Inserted {total_rows} rows...", end="\r")
                chunk = []

        # Insert any remaining rows
        if chunk:
            insert(conn, chunk)
            total_rows += len(chunk)

        print(f"\nTotal rows inserted: {total_rows}")

    conn.close()


def main() -> None:
    if len(sys.argv) < 2:  # noqa: PLR2004
        print("Usage: amazon_to_sqlite <csv_file> <db_file>")
        sys.exit(1)

    csv_file = sys.argv[1]
    db_file = sys.argv[2] if len(sys.argv) > 2 else "amazon.db"  # noqa: PLR2004

    load_csv_to_sqlite(csv_file, db_file)


if __name__ == "__main__":
    main()
