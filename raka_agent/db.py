"""SQLite store for invoice lines, suppliers and dish recipes.

Loads the JSON sample into an in-memory database so the tools can run real SQL.
Swap `load` for a connection to your production Postgres to use live data.
"""

import json
import sqlite3
from pathlib import Path

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data" / "sample_invoices.json"

SCHEMA = """
CREATE TABLE suppliers (id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT);
CREATE TABLE invoice_lines (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    supplier_id TEXT NOT NULL REFERENCES suppliers(id),
    item TEXT NOT NULL,
    unit TEXT NOT NULL,
    qty REAL NOT NULL,
    unit_price REAL NOT NULL
);
CREATE INDEX idx_lines_item_date ON invoice_lines(item, date);
CREATE TABLE dishes (name TEXT PRIMARY KEY, menu_price REAL NOT NULL);
CREATE TABLE dish_ingredients (
    dish TEXT NOT NULL REFERENCES dishes(name),
    item TEXT NOT NULL,
    qty REAL NOT NULL
);
"""


def load(path: Path = DEFAULT_DATA) -> sqlite3.Connection:
    data = json.loads(Path(path).read_text())
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO suppliers VALUES (:id, :name, :email)", data["suppliers"]
    )
    conn.executemany(
        "INSERT INTO invoice_lines (date, supplier_id, item, unit, qty, unit_price) "
        "VALUES (:date, :supplier_id, :item, :unit, :qty, :unit_price)",
        data["invoice_lines"],
    )
    for dish in data["dishes"]:
        conn.execute("INSERT INTO dishes VALUES (?, ?)", (dish["name"], dish["menu_price"]))
        conn.executemany(
            "INSERT INTO dish_ingredients VALUES (?, ?, ?)",
            [(dish["name"], i["item"], i["qty"]) for i in dish["ingredients"]],
        )
    conn.commit()
    return conn
