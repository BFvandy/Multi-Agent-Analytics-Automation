"""
main_multi.py — terminal mode entry point.
Runs the same pipeline.py logic but outputs to terminal.
Useful for debugging without starting a browser.

The reference date is prompted interactively at startup.
"""

import asyncio
from pipeline import run

W = 60


def terminal_emit(event_type, data):
    if event_type == "init":
        print(f"\n{'━' * W}")
        print(f"  Multi-Agent Analytics System")
        print(f"  Analyzing      : {data['period']}")
        print(f"  Reference Date : {data['ref_date']}")
        print(f"{'━' * W}")

    elif event_type == "round":
        print(f"\n{'─' * W}")
        print(f"  ROUND {data['round']} OF 5 — {data['label']}")
        print(f"  Agent: {data['agent'].upper()}")
        print(f"{'─' * W}\n")

    elif event_type == "message":
        agent = data['agent'].upper()
        print(f"\n[{agent}]\n{data['content']}")

    elif event_type == "checkpoint":
        print(f"\n{'═' * W}")
        print(f"  ✋ CHECKPOINT {data['id']} — {data['text']}")
        print(f"{'═' * W}")

    elif event_type == "user_message":
        print(f"\n[YOU] {data['content']}")

    elif event_type == "status":
        print(f"  ... {data['text']}")

    elif event_type == "chart":
        dim = data.get('dimension', '')
        ctype = data.get('chart_type', '')
        print(f"  📊 Chart emitted: {ctype} — {data.get('title', dim)}")
        print(f"\n  ✅ Slide saved: output/{data['filename']}")

    elif event_type == "pipeline_complete":
        print(f"\n{'━' * W}")
        print(f"  ✅ Pipeline complete.")
        print(f"{'━' * W}\n")


def terminal_input():
    return input("  Your input (press Enter to continue): ").strip()


if __name__ == "__main__":
    asyncio.run(run(terminal_emit, terminal_input))