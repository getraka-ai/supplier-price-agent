# Raka Supplier Agent

A small tool-calling agent built on the Claude API. Ask it about your supplier invoices in plain English and it queries a SQL database to answer.

> "Which suppliers raised prices this month?"
> "What does the chicken increase do to my Basil Chicken margin?"
> "Is anyone cheaper for rice? Draft an email asking Bay Produce about it."

![demo](demo.gif)

## How it works

```
question ──> Claude (Messages API, tools=[...])
               │  stop_reason == "tool_use"
               ▼
           run tool ──> SQLite (invoice_lines, suppliers, dishes)
               │  tool_result
               ▼
           Claude ... repeats until it answers in text
```

- `raka_agent/agent.py`: the manual tool-use loop. It caps the number of turns, sends tool errors back as `is_error` so Claude can recover, and tracks token usage.
- `raka_agent/tools.py`: four tools, each a SQL query. They are `list_recent_price_changes`, `get_price_history`, `compare_suppliers` and `get_dish_impact`.
- `raka_agent/db.py`: loads `data/sample_invoices.json` into SQLite. That file holds **synthetic data only**.
- `tests/`: runs offline with a scripted fake client, so no API key is needed.

## Run it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...        # key from a dedicated Console workspace
python -m raka_agent "Which suppliers raised prices in the last 30 days?"
pytest -q
```

To switch models, set `RAKA_MODEL`. The default is `claude-sonnet-5-5`. Use `claude-haiku-5-5` for cheaper runs.

## Next

- Parse real invoice PDFs/photos into `invoice_lines` (Claude vision)
- Postgres instead of SQLite
- Weekly alert when a price jumps more than X%
