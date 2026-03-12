"""
Multi-Agent Analytics System
5-round pipeline with 2 human checkpoints.
"""

import asyncio
import os
from dotenv import load_dotenv
from autogen_core import CancellationToken
from autogen_ext.models.openai import OpenAIChatCompletionClient

from agents_multi import (
    create_master_agent,
    create_analyst_agent_multi,
    create_websearch_agent,
    create_visualization_agent,
)
from tools import REFERENCE_DATE, CURRENT_MONTH, _period_label

load_dotenv()

W = 60  # width


def header(title: str):
    print(f"\n{'━' * W}")
    print(f"  {title}")
    print(f"{'━' * W}")


def agent_label(name: str, description: str):
    print(f"\n{'─' * W}")
    print(f"  🤖 {name}")
    print(f"  {description}")
    print(f"{'─' * W}\n")


def next_step(message: str):
    print(f"\n  ➡️  Next: {message}")


def checkpoint(label: str, hint: str = "") -> str:
    print(f"\n{'═' * W}")
    print(f"  ✋ CHECKPOINT — {label}")
    if hint:
        print(f"  {hint}")
    print(f"{'═' * W}")
    return input("  Your input (or press Enter to continue): ").strip()


def get_text(response) -> str:
    for msg in reversed(response.messages):
        source = getattr(msg, "source", None)
        content = getattr(msg, "content", None)
        if isinstance(content, str) and content.strip() and source not in (None, "user"):
            return content.strip()
    return ""


async def run_until_complete(agent, task: str, trigger: str, token, label: str, max_attempts: int = 3) -> str:
    current_task = task
    full_output = ""

    for attempt in range(max_attempts):
        if attempt > 0:
            print(f"  [Nudging {label}, attempt {attempt + 1}/{max_attempts}...]")

        resp = await agent.run(task=current_task, cancellation_token=token)
        output = get_text(resp)

        if not output:
            print(f"  WARNING: No output from {label}.")
            break

        full_output = output
        print(output)

        if trigger in output:
            return full_output

        current_task = f"Your previous response:\n{output}\n\nYou have not yet written '{trigger}'. Continue from where you left off. End with exactly: {trigger}"

    return full_output


async def main():
    current_period = _period_label(*CURRENT_MONTH)

    print(f"\n{'━' * W}")
    print(f"  MULTI-AGENT ANALYTICS SYSTEM")
    print(f"  Reference Date : {REFERENCE_DATE.strftime('%B %d, %Y')}")
    print(f"  Analyzing      : {current_period}")
    print(f"{'━' * W}")
    print(f"\n  This pipeline has 5 rounds and 2 checkpoints.")
    print(f"\n  Agents:")
    print(f"    1. Data Analyst Agent   - runs quantitative analysis")
    print(f"    2. Master Agent         - identifies search topics + writes narrative")
    print(f"    3. Web Search Agent     - finds external context")
    print(f"    4. Visualization Agent  - generates PowerPoint slide")

    model_client = OpenAIChatCompletionClient(
        model="gpt-4o",
        api_key=os.environ.get("OPENAI_API_KEY"),
    )

    master        = create_master_agent(model_client)
    analyst       = create_analyst_agent_multi(model_client)
    websearch     = create_websearch_agent(model_client)
    visualization = create_visualization_agent(model_client)
    token         = CancellationToken()

    # ── Round 1: Analyst ──────────────────────────────────────────
    header("ROUND 1 OF 5 - Quantitative Analysis")
    agent_label(
        "DATA ANALYST AGENT",
        "Running 5-step analysis on your credit card transaction data"
    )

    analyst_output = await run_until_complete(
        analyst,
        task=f"Analyze credit card transaction data for {current_period}. Reference date is {REFERENCE_DATE.strftime('%B %d, %Y')}. Run ALL 5 steps. Show results after each tool call. End with Key Findings then write exactly: ANALYSIS COMPLETE",
        trigger="ANALYSIS COMPLETE",
        token=token,
        label="Data Analyst Agent",
    )

    next_step("Web Search Agent will search for external factors explaining these trends.")

    # ── CHECKPOINT 1 ──────────────────────────────────────────────
    user_input = checkpoint(
        "Review the Data Analyst Agent's findings above.",
        "Press Enter to proceed to web research, or type feedback to refine the analysis."
    )
    feedback = f"\nUser feedback: {user_input}" if user_input else ""

    # ── Round 2: Master identifies queries ────────────────────────
    header("ROUND 2 OF 5 - Identifying Search Topics")
    agent_label(
        "MASTER AGENT",
        "Identifying key drivers and formulating web search queries"
    )

    master_r2_resp = await master.run(
        task=f"""Here is the Data Analyst's quantitative analysis for {current_period}:

{analyst_output}
{feedback}

Based on these findings, identify the key driver and write 2-3 specific web search queries
to find external factors explaining this trend. End with: SEARCH QUERIES READY""",
        cancellation_token=token,
    )
    master_output2 = get_text(master_r2_resp)
    print(master_output2)

    next_step("Web Search Agent will now run these queries against the web.")

    # ── Round 3: WebSearch ────────────────────────────────────────
    header("ROUND 3 OF 5 - Web Research")
    agent_label(
        "WEB SEARCH AGENT",
        "Searching the web for external context and industry trends"
    )

    search_output = await run_until_complete(
        websearch,
        task=f"""The Master Agent has identified these search queries based on credit card analytics for {current_period}:

{master_output2}

Run each query using the web_search tool. Synthesize findings into a clear external context summary.
End with: SEARCH COMPLETE""",
        trigger="SEARCH COMPLETE",
        token=token,
        label="Web Search Agent",
    )

    next_step("Master Agent will combine data findings with web research into an executive narrative.")

    # ── Round 4: Master narrative + slide spec ────────────────────
    header("ROUND 4 OF 5 - Executive Narrative + Slide Spec")
    agent_label(
        "MASTER AGENT",
        "Synthesizing quantitative findings + external context into executive narrative"
    )

    master_r4_resp = await master.run(
        task=f"""You are writing an executive summary combining two inputs:

QUANTITATIVE ANALYSIS ({current_period}):
{analyst_output}

EXTERNAL CONTEXT (web research):
{search_output}

Write a 3-5 sentence executive narrative combining what happened (data) and why (external context).
Then output the complete slide JSON spec with ALL segments in chart_data and table_data.
End with: NARRATIVE READY - AWAITING YOUR APPROVAL""",
        cancellation_token=token,
    )
    master_output4 = get_text(master_r4_resp)
    print(master_output4)

    next_step("Visualization Agent will generate your PowerPoint slide.")

    # ── CHECKPOINT 2 ──────────────────────────────────────────────
    user_input2 = checkpoint(
        "Review the narrative and slide spec above.",
        "Press Enter to generate the slide, or type edits (e.g. 'change the title to...')"
    )
    edits = f"\nUser edits: {user_input2}" if user_input2 else ""

    # ── Round 5: Visualization ────────────────────────────────────
    header("ROUND 5 OF 5 - Slide Generation")
    agent_label(
        "VISUALIZATION AGENT",
        "Generating your executive PowerPoint slide"
    )

    viz_output = await run_until_complete(
        visualization,
        task=f"""Generate a PowerPoint slide using this spec:

{master_output4}
{edits}

Use output filename: analytics_{REFERENCE_DATE.strftime('%Y%m')}.pptx
End with: VISUALIZATION COMPLETE""",
        trigger="VISUALIZATION COMPLETE",
        token=token,
        label="Visualization Agent",
    )

    print(f"\n{'━' * W}")
    print(f"  PIPELINE COMPLETE")
    print(f"  Slide saved to: output/analytics_{REFERENCE_DATE.strftime('%Y%m')}.pptx")
    print(f"{'━' * W}\n")


if __name__ == "__main__":
    asyncio.run(main())