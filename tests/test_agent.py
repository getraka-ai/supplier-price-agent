"""Runs offline: tools hit the sample DB, the agent loop uses a scripted fake client."""

import json
from types import SimpleNamespace as NS

import pytest

from raka_agent import db, tools
from raka_agent.agent import ask


@pytest.fixture
def conn():
    return db.load()


# ---------- tools ----------

def test_recent_changes_sorted_and_correct(conn):
    out = tools.list_recent_price_changes(conn, days=30)
    assert out["as_of"] == "2026-09-15"
    items = [(c["supplier"], c["item"]) for c in out["changes"]]
    assert items[0] == ("Bay Produce Co.", "thai basil")  # +10.8% is the biggest
    rice = next(c for c in out["changes"] if c["item"] == "jasmine rice 50lb")
    assert (rice["old_price"], rice["new_price"], rice["pct_change"]) == (48.0, 52.5, 9.4)
    assert all(c["item"] != "coconut milk 13.5oz" for c in out["changes"])  # unchanged price


def test_min_pct_filter(conn):
    out = tools.list_recent_price_changes(conn, days=30, min_pct=10)
    assert [c["item"] for c in out["changes"]] == ["thai basil"]


def test_compare_suppliers_cheapest_first(conn):
    out = tools.compare_suppliers(conn, "rice")
    assert out["cheapest"] == "Pacific Asian Foods"
    assert [o["latest_price"] for o in out["offers"]] == [49.0, 52.5]


def test_dish_impact(conn):
    out = tools.get_dish_impact(conn, "chicken")
    basil = next(d for d in out["dishes"] if d["dish"] == "Basil Chicken")
    assert basil["plate_cost_now"] > basil["plate_cost_before"]
    deltas = {i["item"]: i["delta"] for i in basil["ingredients"]}
    assert deltas["chicken thigh boneless"] == pytest.approx(0.104)  # 0.4 lb x $0.26
    assert set(deltas) == {"chicken thigh boneless", "thai basil", "jasmine rice 50lb"}


def test_bad_item_lists_known_items(conn):
    with pytest.raises(tools.ToolError, match="Known items"):
        tools.get_price_history(conn, "lobster")


# ---------- agent loop ----------

class FakeClient:
    """Plays back scripted responses and records what the agent sent."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs, default=lambda o: vars(o))))
        return self.responses.pop(0)


def _resp(stop_reason, *blocks):
    return NS(stop_reason=stop_reason, content=list(blocks), usage=NS(input_tokens=100, output_tokens=20))


def test_loop_runs_tool_and_returns_answer(conn):
    client = FakeClient([
        _resp("tool_use", NS(type="tool_use", id="t1", name="compare_suppliers", input={"item": "rice"})),
        _resp("end_turn", NS(type="text", text="Switch rice to Pacific Asian Foods.")),
    ])
    result = ask("Where should I buy rice?", client=client, conn=conn)

    assert result["answer"] == "Switch rice to Pacific Asian Foods."
    assert result["tool_calls"] == [{"name": "compare_suppliers", "input": {"item": "rice"}, "is_error": False}]
    assert result["usage"] == {"input_tokens": 200, "output_tokens": 40}

    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert tool_result["tool_use_id"] == "t1"
    assert json.loads(tool_result["content"])["cheapest"] == "Pacific Asian Foods"


def test_loop_reports_tool_errors_to_claude(conn):
    client = FakeClient([
        _resp("tool_use", NS(type="tool_use", id="t1", name="get_price_history", input={"item": "lobster"})),
        _resp("end_turn", NS(type="text", text="You don't buy lobster.")),
    ])
    result = ask("Lobster prices?", client=client, conn=conn)
    assert result["tool_calls"][0]["is_error"] is True
    assert client.calls[1]["messages"][-1]["content"][0]["is_error"] is True
