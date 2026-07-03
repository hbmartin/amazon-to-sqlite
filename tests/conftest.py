import csv
import sqlite3
from pathlib import Path

import pytest

from amazon_to_sqlite.db import FIELD_TYPES

HEADERS = list(FIELD_TYPES)


def make_row(**overrides: str) -> list[str]:
    values = {
        "Website": "Amazon.com",
        "Order ID": "111-2223334-5556667",
        "Order Date": "2023-08-12T20:23:53Z",
        "Purchase Order Number": "Not Applicable",
        "Currency": "USD",
        "Unit Price": "$12.99",
        "Unit Price Tax": "1.04",
        "Shipping Charge": "0",
        "Total Discounts": "0",
        "Total Owed": "14.03",
        "Shipment Item Subtotal": "12.99",
        "Shipment Item Subtotal Tax": "1.04",
        "ASIN": "0306406152",
        "Product Condition": "New",
        "Quantity": "1",
        "Payment Instrument Type": "Visa",
        "Order Status": "Closed",
        "Shipment Status": "Shipped",
        "Ship Date": "2023-08-13T01:00:00Z",
        "Shipping Option": "std-us",
        "Shipping Address": "123 Main St",
        "Billing Address": "123 Main St",
        "Carrier Name & Tracking Number": "USPS(9400111899560000000000)",
        "Product Name": "An Example Book",
        "Gift Message": "Not Available",
        "Gift Sender Name": "Not Available",
        "Gift Recipient Contact Details": "Not Available",
        "Item Serial Number": "Not Applicable",
    }
    unknown = set(overrides) - set(HEADERS)
    if unknown:
        raise ValueError(
            "Unknown order-history field override(s): " + ", ".join(sorted(unknown)),
        )
    values.update(overrides)
    return [values[h] for h in HEADERS]


def write_csv(
    path: Path,
    rows: list[list[str]],
    headers: list[str] | None = None,
) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers if headers is not None else HEADERS)
        writer.writerows(rows)
    return path


@pytest.fixture
def conn() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


@pytest.fixture
def orders_csv(tmp_path: Path) -> Path:
    rows = [
        make_row(),
        make_row(
            **{
                "Order ID": "111-0000000-0000001",
                "Order Date": "2024-01-02T03:04:05Z",
                "ASIN": "B08N5WRWNW",
                "Product Name": "Echo Dot",
                "Unit Price": "$49.99",
                "Total Owed": "53.99",
            },
        ),
    ]
    return write_csv(tmp_path / "Retail.OrderHistory.1.csv", rows)
