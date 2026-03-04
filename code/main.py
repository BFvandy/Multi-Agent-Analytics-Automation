"""
Autonomous Multi-Agent Analytics System - POC
Analysis window is driven by REFERENCE_DATE in .env or tools.py.
"""

import asyncio
import os
from dotenv import load_dotenv
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_ext.models.openai import OpenAIChatCompletionClient

from agents import create_analyst_agent, create_manager_agent
from tools import REFERENCE_DATE, CURRENT_MONTH, _period_label

load_dotenv()


async def main():
    current_period = _period_label(*CURRENT_MONTH)

    print("=" * 60)
    print("Autonomous Analytics System — POC")
    print(f"Reference Date : {REFERENCE_DATE.strftime('%B %d, %Y')}")
    print(f"Analyzing      : {current_period}")
    print("=" * 60)
    print()

    model_client = OpenAIChatCompletionClient(
        model="gpt-4o-mini",
        api_key=os.environ.get("OPENAI_API_KEY"),
    )

    analyst = create_analyst_agent(model_client)
    manager = create_manager_agent(model_client)

    # Terminate on APPROVED or after 16 messages
    termination = (
        TextMentionTermination("FINAL APPROVED") | MaxMessageTermination(16)
    )

    team = RoundRobinGroupChat(
        participants=[analyst, manager],
        termination_condition=termination,
    )

    task = f"""
    Analyze credit card transaction data for {current_period}.
    Reference date is {REFERENCE_DATE.strftime('%B %d, %Y')}.

    Run ALL 5 steps of your analytical workflow completely before handing off:
    1. Confirm schema and analysis periods via get_schema_info
    2. Overall spend: MoM delta, % change, transaction volume
    3. YoY + CTG decomposition by: Exp Type and Card Type
    4. 7-day rolling average and rolling avg YoY
    5. Identify the biggest CTG mover and drill into it

    Complete ALL 5 steps. End with Key Findings and READY FOR REVIEW.
    Do not stop between steps. Do not narrate tool calls — just run them and report results.
    """

    print("Starting agent conversation...\n")
    print("-" * 60)

    async for message in team.run_stream(task=task):
        source = getattr(message, "source", None)
        content = getattr(message, "content", None)

        # Skip non-text content (lists = raw tool calls/results)
        if content is None or isinstance(content, list):
            continue

        content_str = str(content).strip()
        if not content_str:
            continue

        # Skip raw function call / execution noise
        if content_str.startswith("[FunctionCall") or content_str.startswith("[FunctionExecution"):
            continue

        # Only show Analyst and Manager
        if source in ("Analyst", "Manager"):
            print(f"\n{'=' * 60}")
            print(f"[ {source.upper()} ]")
            print(f"{'=' * 60}")
            print(content_str)

    print("\n" + "=" * 60)
    print("Analysis complete.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
