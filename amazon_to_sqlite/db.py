from sqlite3 import Connection

_field_types = {
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

fields = [
    "".join(c if c.isalnum() or c == "_" else "_" for c in field.replace(" ", "_"))
    for field in _field_types
]

table_name = "amazon_orders"


def create_table_statement() -> str:
    typed_fields = []
    for field, data_type in _field_types.items():
        # Replace spaces with underscores and remove any non-alphanumeric characters
        safe_field_name = "".join(
            c if c.isalnum() or c == "_" else "_" for c in field.replace(" ", "_")
        )
        typed_fields.append(f'"{safe_field_name}" {data_type}')

    fields_str = ",\n    ".join(typed_fields)
    return f"CREATE TABLE IF NOT EXISTS {table_name} ({fields_str});"


def create_table(conn: Connection) -> None:
    conn.cursor().execute(create_table_statement())
    conn.commit()


def noneify(data: list[str]) -> list[str | None]:
    return [d if d not in ("Not Applicable", "Not Available") else None for d in data]


def insert(conn: Connection, rows: list[list[str]]) -> None:
    placeholders = ", ".join(["?" for _ in fields])
    insert_query = f'INSERT INTO "{table_name}" VALUES ({placeholders})'  # noqa: S608
    conn.executemany(insert_query, [noneify(row) for row in rows])
    conn.commit()
