"""Tools the agent can call. Each one is plain SQL over the invoice database.

TOOL_SCHEMAS is what Claude sees. TOOL_FUNCS maps the same names to Python.
Every tool returns a JSON-serializable dict.
"""

import sqlite3
from datetime import date, timedelta


class ToolError(Exception):
    """Raised for bad input. The agent loop reports it back to Claude as is_error."""


# ---------- helpers ----------

def _as_of(conn: sqlite3.Connection) -> date:
    """Latest invoice date. 'Recent' is measured from here so the demo data never goes stale."""
    (latest,) = conn.execute("SELECT MAX(date) FROM invoice_lines").fetchone()
    return date.fromisoformat(latest)


def _resolve_item(conn: sqlite3.Connection, item: str) -> str:
    """Match a loose name like 'rice' to one catalog item."""
    rows = conn.execute(
        "SELECT DISTINCT item FROM invoice_lines WHERE item LIKE ? ORDER BY item",
        (f"%{item.strip().lower()}%",),
    ).fetchall()
    names = [r["item"] for r in rows]
    if not names:
        known = [r["item"] for r in conn.execute("SELECT DISTINCT item FROM invoice_lines ORDER BY item")]
        raise ToolError(f"No item matches '{item}'. Known items: {', '.join(known)}")
    if len(names) > 1:
        raise ToolError(f"'{item}' is ambiguous. Pick one of: {', '.join(names)}")
    return names[0]


def _pct(old: float, new: float) -> float:
    return round((new - old) / old * 100, 1) if old else 0.0


def _baseline_and_latest(conn, item, cutoff, supplier_id=None):
    """Price at or before the cutoff (else the earliest), and the latest price."""
    where, args = "item = ?", [item]
    if supplier_id:
        where += " AND supplier_id = ?"
        args.append(supplier_id)
    latest = conn.execute(
        f"SELECT date, unit_price FROM invoice_lines WHERE {where} ORDER BY date DESC LIMIT 1", args
    ).fetchone()
    base = conn.execute(
        f"SELECT date, unit_price FROM invoice_lines WHERE {where} AND date <= ? "
        "ORDER BY date DESC LIMIT 1",
        args + [cutoff],
    ).fetchone() or conn.execute(
        f"SELECT date, unit_price FROM invoice_lines WHERE {where} ORDER BY date ASC LIMIT 1", args
    ).fetchone()
    return base, latest


# ---------- tools ----------

def list_recent_price_changes(conn, days: int = 30, min_pct: float = 0.0) -> dict:
    if days <= 0:
        raise ToolError("days must be positive")
    as_of = _as_of(conn)
    cutoff = (as_of - timedelta(days=days)).isoformat()
    pairs = conn.execute(
        "SELECT DISTINCT l.supplier_id, s.name AS supplier, l.item, l.unit "
        "FROM invoice_lines l JOIN suppliers s ON s.id = l.supplier_id"
    ).fetchall()
    changes = []
    for p in pairs:
        base, latest = _baseline_and_latest(conn, p["item"], cutoff, p["supplier_id"])
        pct = _pct(base["unit_price"], latest["unit_price"])
        if latest["date"] >= cutoff and pct != 0 and abs(pct) >= min_pct:
            changes.append({
                "supplier": p["supplier"],
                "item": p["item"],
                "unit": p["unit"],
                "old_price": base["unit_price"],
                "old_date": base["date"],
                "new_price": latest["unit_price"],
                "new_date": latest["date"],
                "pct_change": pct,
            })
    changes.sort(key=lambda c: c["pct_change"], reverse=True)
    return {"as_of": as_of.isoformat(), "window_days": days, "changes": changes}


def get_price_history(conn, item: str) -> dict:
    name = _resolve_item(conn, item)
    rows = conn.execute(
        "SELECT l.date, s.name AS supplier, l.unit, l.qty, l.unit_price "
        "FROM invoice_lines l JOIN suppliers s ON s.id = l.supplier_id "
        "WHERE l.item = ? ORDER BY l.date",
        (name,),
    ).fetchall()
    return {"item": name, "history": [dict(r) for r in rows]}


def compare_suppliers(conn, item: str) -> dict:
    name = _resolve_item(conn, item)
    rows = conn.execute(
        """
        SELECT s.name AS supplier, s.email, l.unit, l.unit_price AS latest_price, l.date AS latest_date
        FROM invoice_lines l
        JOIN suppliers s ON s.id = l.supplier_id
        WHERE l.item = ?
          AND l.date = (SELECT MAX(date) FROM invoice_lines x
                        WHERE x.item = l.item AND x.supplier_id = l.supplier_id)
        ORDER BY l.unit_price ASC
        """,
        (name,),
    ).fetchall()
    offers = [dict(r) for r in rows]
    return {"item": name, "offers": offers, "cheapest": offers[0]["supplier"] if offers else None}


def get_dish_impact(conn, item: str, days: int = 30) -> dict:
    name = _resolve_item(conn, item)
    cutoff = (_as_of(conn) - timedelta(days=days)).isoformat()
    dishes = conn.execute(
        "SELECT d.name, d.menu_price FROM dishes d JOIN dish_ingredients i ON i.dish = d.name "
        "WHERE i.item = ? ORDER BY d.name",
        (name,),
    ).fetchall()
    out = []
    for d in dishes:
        old_cost = new_cost = 0.0
        breakdown = []
        for ing in conn.execute("SELECT item, qty FROM dish_ingredients WHERE dish = ?", (d["name"],)):
            base, latest = _baseline_and_latest(conn, ing["item"], cutoff)
            before = ing["qty"] * base["unit_price"]
            now = ing["qty"] * latest["unit_price"]
            old_cost += before
            new_cost += now
            breakdown.append({
                "item": ing["item"],
                "cost_before": round(before, 3),
                "cost_now": round(now, 3),
                "delta": round(now - before, 3),
            })
        out.append({
            "ingredients": breakdown,
            "dish": d["name"],
            "menu_price": d["menu_price"],
            "plate_cost_before": round(old_cost, 2),
            "plate_cost_now": round(new_cost, 2),
            "food_cost_pct_before": round(old_cost / d["menu_price"] * 100, 1),
            "food_cost_pct_now": round(new_cost / d["menu_price"] * 100, 1),
        })
    return {"item": name, "window_days": days, "dishes": out}


# ---------- registry ----------

TOOL_SCHEMAS = [
    {
        "name": "list_recent_price_changes",
        "description": (
            "List supplier price changes in the last N days, measured from the latest invoice. "
            "Use this first when the user asks what went up or which suppliers raised prices. "
            "Returns old and new unit price and percent change, biggest increase first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Lookback window in days. Default 30."},
                "min_pct": {"type": "number", "description": "Only return changes at least this large, in percent."},
            },
        },
    },
    {
        "name": "get_price_history",
        "description": "Every invoice line for one item across all suppliers, oldest first. Accepts a partial name like 'rice'.",
        "input_schema": {
            "type": "object",
            "properties": {"item": {"type": "string", "description": "Item name or part of it."}},
            "required": ["item"],
        },
    },
    {
        "name": "compare_suppliers",
        "description": "Latest unit price for one item from each supplier that sells it, cheapest first, with supplier email.",
        "input_schema": {
            "type": "object",
            "properties": {"item": {"type": "string", "description": "Item name or part of it."}},
            "required": ["item"],
        },
    },
    {
        "name": "get_dish_impact",
        "description": (
            "For every menu dish that uses the item, plate cost and food cost percent before and after "
            "the last N days of price changes, with a per-ingredient breakdown of what changed. "
            "One call covers all ingredients of those dishes, so don't call it again for another "
            "ingredient of the same dish."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "description": "Item name or part of it."},
                "days": {"type": "integer", "description": "Lookback window in days. Default 30."},
            },
            "required": ["item"],
        },
    },
]

TOOL_FUNCS = {
    "list_recent_price_changes": list_recent_price_changes,
    "get_price_history": get_price_history,
    "compare_suppliers": compare_suppliers,
    "get_dish_impact": get_dish_impact,
}
