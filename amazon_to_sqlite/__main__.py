import sqlite3
import csv
import sys
from sqlite3 import Connection, Cursor


def create_table(cursor: Cursor, table_name: str, headers):
    # Create a table with columns matching the CSV headers
    columns = ', '.join([f'"{header}" TEXT' for header in headers])
    cursor.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({columns})')


def load_csv_to_sqlite(csv_file: str, db_file: str, table_name: str, chunk_size=10000):
    conn: Connection = sqlite3.connect(db_file)
    cursor: Cursor = conn.cursor()

    with open(csv_file, 'r', newline='', encoding='utf-8') as csvfile:
        csv_reader = csv.reader(csvfile)
        headers = next(csv_reader)  # Read the header row

        create_table(cursor, table_name, headers)

        # Prepare the INSERT statement
        placeholders = ', '.join(['?' for _ in headers])
        insert_query = f'INSERT INTO "{table_name}" VALUES ({placeholders})'

        # Insert data in chunks
        chunk = []
        total_rows = 0
        for row in csv_reader:
            chunk.append(row)
            if len(chunk) == chunk_size:
                cursor.executemany(insert_query, chunk)
                conn.commit()
                total_rows += len(chunk)
                print(f"Inserted {total_rows} rows...", end='\r')
                chunk = []

        # Insert any remaining rows
        if chunk:
            cursor.executemany(insert_query, chunk)
            conn.commit()
            total_rows += len(chunk)

        print(f"\nTotal rows inserted: {total_rows}")

    conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: amazon_to_sqlite <csv_file> <db_file> <table_name>")
        sys.exit(1)

    csv_file = sys.argv[1]
    db_file = sys.argv[2]
    table_name = sys.argv[3]

    load_csv_to_sqlite(csv_file, db_file, table_name)