import sqlite3
import csv
import sys
from sqlite3 import Connection, Cursor

from amazon_to_sqlite.db import create_table, insert


def load_csv_to_sqlite(
    csv_file: str, db_file: str, table_name: str = "orders", chunk_size=100
):
    conn: Connection = sqlite3.connect(db_file)
    create_table(conn)

    with open(csv_file, "r", newline="", encoding="utf-8-sig") as csvfile:
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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: amazon_to_sqlite <csv_file> <db_file>")
        sys.exit(1)

    csv_file = sys.argv[1]
    db_file = sys.argv[2] if len(sys.argv) > 2 else "amazon.db"

    load_csv_to_sqlite(csv_file, db_file)
