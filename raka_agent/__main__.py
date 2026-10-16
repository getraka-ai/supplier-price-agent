"""CLI: python -m raka_agent "Which suppliers raised prices this month?" """

import sys

from .agent import DEFAULT_MODEL, ask


def show(markdown: str) -> None:
    """Render tables and bold in the terminal if `rich` is installed, else print raw."""
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        Console().print(Markdown(markdown))
    except ImportError:
        print(markdown)


def main() -> None:
    question = " ".join(sys.argv[1:]) or "Which suppliers raised prices in the last 30 days, and what should I do?"
    print(f"Q: {question}\n")
    result = ask(question, verbose=True)
    print()
    show(result["answer"])
    u = result["usage"]
    print(f"\n[{DEFAULT_MODEL} | {u['input_tokens']} in / {u['output_tokens']} out tokens]")


if __name__ == "__main__":
    main()
