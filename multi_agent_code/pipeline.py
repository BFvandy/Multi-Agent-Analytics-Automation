"""
pipeline.py — the actual multi-agent logic, decoupled from both
terminal printing and the Flask server.

emit(event_type, data)  → sends an event to whoever is listening
wait_for_input()        → blocks until the user responds
"""

import asyncio
import os
import re
from dotenv import load_dotenv
from autogen_core import CancellationToken
from autogen_ext.models.openai import OpenAIChatCompletionClient

import json as _json

import tools
from tools import _period_label
from agents_multi import (
    create_master_agent,
    create_analyst_agent_multi,
    create_websearch_agent,
    create_visualization_agent,
)

load_dotenv()

# ── Chart result cache ────────────────────────────────────────
# get_trend_charts results are stored here as raw dicts so the
# pipeline can emit them directly — bypassing LLM serialization.
_chart_cache: list[dict] = []


def _make_intercepting_analyst(model_client, emit_fn):
    """
    Creates an analyst agent whose get_trend_charts tool is wrapped
    to intercept results and emit chart events directly.
    """
    import functools
    import tools as _tools
    from autogen_agentchat.agents import AssistantAgent
    from prompts_multi import ANALYST_MULTI_SYSTEM_PROMPT

    original_get_trend_charts = _tools.get_trend_charts

    @functools.wraps(original_get_trend_charts)
    def intercepted_get_trend_charts(dimension: str) -> str:
        print(f"[chart interceptor] get_trend_charts called for dimension='{dimension}'")
        raw_json = original_get_trend_charts(dimension)
        data = _json.loads(raw_json)

        # Emit YoY line chart directly with raw numbers
        emit_fn("chart", {
            "chart_type": "line",
            "title":      f"YoY % by {dimension} — 12 Months",
            "dimension":  dimension,
            "months":     data["months"],
            "segments":   data["segments"],
            "series":     data["yoy_series"],
        })

        # Emit CTG stacked bar chart directly with raw numbers
        emit_fn("chart", {
            "chart_type": "stacked_bar",
            "title":      f"CTG % by {dimension} — 12 Months",
            "dimension":  dimension,
            "months":     data["months"],
            "segments":   data["segments"],
            "series":     data["ctg_series"],
        })

        # Return minimal summary — no raw numbers so LLM can't corrupt them
        return _json.dumps({
            "status":    "chart_emitted",
            "dimension": dimension,
            "window":    data.get("window", ""),
            "segments":  data["segments"],
            "note":      "Charts sent to UI. Do NOT reproduce the numbers. Just confirm the charts were generated.",
        })

    # Ensure autogen sees the correct annotations (functools.wraps copies most, but be explicit)
    intercepted_get_trend_charts.__annotations__ = original_get_trend_charts.__annotations__.copy()

    return AssistantAgent(
        name="Analyst",
        model_client=model_client,
        system_message=ANALYST_MULTI_SYSTEM_PROMPT,
        tools=[
            _tools.get_schema_info,
            _tools.get_overall_monthly_summary,
            _tools.get_dimension_decomposition,
            _tools.get_segment_decomposition,
            _tools.drill_down_segment,
        ],
        reflect_on_tool_use=True,
    )


def _prompt_reference_date() -> str:
    """
    Prompt the user for a reference date at startup.
    The analysis covers the month immediately before this date.
    Keeps asking until a valid YYYY-MM-01 date is entered.
    """
    print("\n" + "═" * 60)
    print("  Multi-Agent Analytics System")
    print("═" * 60)
    print("\n  The reference date determines which month is analysed.")
    print("  Example: enter 2025-03-01 to analyse February 2025.\n")

    while True:
        raw = input("  Enter reference date (YYYY-MM-01): ").strip()
        if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])-01", raw):
            return raw
        print(f"  ⚠️  '{raw}' is not valid. Please use YYYY-MM-01 format (e.g. 2025-03-01).")


def get_text(response) -> str:
    for msg in reversed(response.messages):
        source  = getattr(msg, "source", None)
        content = getattr(msg, "content", None)
        if isinstance(content, str) and content.strip() and source not in (None, "user"):
            return content.strip()
    return ""


async def run_until_complete(agent, task, trigger, token, label, emit, max_attempts=3):
    current_task    = task
    accumulated     = []
    for attempt in range(max_attempts):
        if attempt > 0:
            emit("status", {"text": f"Nudging {label} (attempt {attempt+1})..."})
        resp   = await agent.run(task=current_task, cancellation_token=token)
        output = get_text(resp)
        if not output:
            emit("status", {"text": f"No output from {label}"})
            break
        accumulated.append(output)
        emit("message", {"agent": label, "content": output})
        print(f"[pipeline] {label} attempt {attempt+1}: trigger '{trigger}' {'FOUND' if trigger in output else 'NOT FOUND'} (len={len(output)})")
        print(f"[pipeline] {label} first 120 chars: {repr(output[:120])}")
        if trigger in output:
            return "\n\n".join(accumulated)
        current_task = (
            f"Your previous response:\n{output}\n\n"
            f"You have not yet written '{trigger}'. "
            f"Continue from where you left off and end with exactly: {trigger}"
        )
    return "\n\n".join(accumulated)


async def run(emit, wait_for_input, reference_date: str | None = None):
    """
    Main pipeline entry point.

    Args:
        emit:           Callback for streaming events to the UI or terminal.
        wait_for_input: Callable (sync or async) that returns user input string.
        reference_date: Optional YYYY-MM-01 string. If None, the user is prompted
                        interactively at startup.
    """
    print("[pipeline] run() started")

    # ── Set reference date ────────────────────────────────────
    if reference_date is None:
        reference_date = _prompt_reference_date()

    tools.init(reference_date)

    current_period = _period_label(*tools.CURRENT_MONTH)
    print(f"[pipeline] period: {current_period}")

    emit("init", {
        "period":   current_period,
        "ref_date": tools.REFERENCE_DATE.strftime("%B %d, %Y"),
    })

    model_client  = OpenAIChatCompletionClient(
        model="gpt-4o",
        api_key=os.environ.get("OPENAI_API_KEY"),
    )
    master        = create_master_agent(model_client)
    analyst       = _make_intercepting_analyst(model_client, emit)   # ← intercepting wrapper
    websearch     = create_websearch_agent(model_client)
    visualization = create_visualization_agent(model_client)
    token         = CancellationToken()

    # ── Round 1a: Analyst — Steps 1-3 (summary + decomposition + charts) ────────
    emit("round", {"round": 1, "label": "Quantitative Analysis — Summary & Decomposition", "agent": "analyst"})

    analyst_steps123 = await run_until_complete(
        analyst,
        task=(
            f"Analyze credit card transaction data for {current_period}. "
            f"Reference date is {tools.REFERENCE_DATE.strftime('%B %d, %Y')}. "
            "Run PHASE 1 only: Steps 1, 2, and 3. "
            "Step 1: call get_schema_info. "
            "Step 2: call get_overall_monthly_summary. "
            "Step 3: call get_dimension_decomposition for 'Card Type' then 'Exp Type'. "
            "Present summary tables and state TOP CARD TYPE DRIVER and TOP EXP TYPE DRIVER. "
            "End with exactly: STEPS 1-3 COMPLETE"
        ),
        trigger="STEPS 1-3 COMPLETE",
        token=token,
        label="analyst",
        emit=emit,
        max_attempts=4,
    )

    # ── Emit trend charts directly from pipeline ──────────────────────────────
    emit("round", {"round": 1, "label": "12-Month Trend Charts", "agent": "analyst"})
    emit("status", {"text": "Generating 12-month trend charts…"})
    for dimension in ["Card Type", "Exp Type"]:
        try:
            raw = tools.get_trend_charts(dimension)
            data = _json.loads(raw)
            emit("chart", {
                "chart_type": "line",
                "title":      f"YoY % by {dimension} — 12 Months",
                "dimension":  dimension,
                "months":     data["months"],
                "segments":   data["segments"],
                "series":     data["yoy_series"],
            })
            emit("chart", {
                "chart_type": "stacked_bar",
                "title":      f"CTG % by {dimension} — 12 Months",
                "dimension":  dimension,
                "months":     data["months"],
                "segments":   data["segments"],
                "series":     data["ctg_series"],
            })
            print(f"[pipeline] charts emitted for {dimension}")
        except Exception as e:
            print(f"[pipeline] chart error for {dimension}: {e}")
            emit("status", {"text": f"Chart error ({dimension}): {e}"})

    # ── Round 1b: Analyst — Step 4 (key driver deep-dive) ────────────────────
    emit("round", {"round": 1, "label": "Key Driver Deep-Dive", "agent": "analyst"})

    analyst_step4 = await run_until_complete(
        analyst,
        task=(
            f"You have completed Steps 1-3 for {current_period}. Here is your prior output:\n\n"
            f"{analyst_steps123}\n\n"
            "Now run Step 4: identify the TOP CARD TYPE DRIVER from your Step 3 output above, "
            "then call `get_segment_decomposition` with that exact card type value. "
            "Present the full Exp Type breakdown table within that card segment. "
            "State the TOP SUB-DRIVER and write an ANALYTICAL OBSERVATION. "
            "Then write Key Findings (3 bullets across all steps). "
            "End with exactly: ANALYSIS COMPLETE"
        ),
        trigger="ANALYSIS COMPLETE",
        token=token,
        label="analyst",
        emit=emit,
        max_attempts=3,
    )

    # Combine both parts so downstream agents have the full picture
    analyst_output = analyst_steps123 + "\n\n" + analyst_step4

    emit("checkpoint", {
        "id":   1,
        "text": "Review the analysis above. Press Continue or type feedback.",
    })
    user_input = await wait_for_input() if asyncio.iscoroutinefunction(wait_for_input) else wait_for_input()
    emit("user_message", {"content": user_input or "Looks good, continue."})
    feedback = f"\nUser feedback: {user_input}" if user_input else ""

    # ── Round 2: Master search queries ────────────────────────
    emit("round", {"round": 2, "label": "Identifying Search Topics", "agent": "master"})

    master_r2 = await master.run(
        task=(
            f"Here is the Data Analyst's quantitative analysis for {current_period}:\n\n"
            f"{analyst_output}{feedback}\n\n"
            "Identify the key driver and write 2-3 specific web search queries "
            "to find external factors explaining this trend. End with: SEARCH QUERIES READY"
        ),
        cancellation_token=token,
    )
    master_output2 = get_text(master_r2)
    emit("message", {"agent": "master", "content": master_output2})

    # ── Round 3: WebSearch ────────────────────────────────────
    emit("round", {"round": 3, "label": "Web Research", "agent": "search"})

    search_output = await run_until_complete(
        websearch,
        task=(
            f"The Master Agent has identified these search queries for {current_period}:\n\n"
            f"{master_output2}\n\n"
            "Run each query using the web_search tool. "
            "Synthesize findings into a clear external context summary. "
            "End with: SEARCH COMPLETE"
        ),
        trigger="SEARCH COMPLETE",
        token=token,
        label="search",
        emit=emit,
    )

    # ── Round 4: Master narrative ─────────────────────────────
    emit("round", {"round": 4, "label": "Executive Narrative + Slide Spec", "agent": "master"})

    master_r4 = await master.run(
        task=(
            f"You are writing an executive summary combining two inputs:\n\n"
            f"QUANTITATIVE ANALYSIS ({current_period}):\n{analyst_output}\n\n"
            f"EXTERNAL CONTEXT (web research):\n{search_output}\n\n"
            "Write a 3-5 sentence executive narrative combining what happened and why. "
            "Then output the complete slide JSON spec with ALL segments. "
            "End with: NARRATIVE READY — AWAITING YOUR APPROVAL"
        ),
        cancellation_token=token,
    )
    master_output4 = get_text(master_r4)
    emit("message", {"agent": "master", "content": master_output4})

    emit("checkpoint", {
        "id":   2,
        "text": "Review the narrative and slide spec. Press Continue to generate the slide, or type a request for deeper analysis.",
    })
    user_input2 = await wait_for_input() if asyncio.iscoroutinefunction(wait_for_input) else wait_for_input()
    emit("user_message", {"content": user_input2 or "Looks good, generate the slide."})

    # ── Optional: additional analyst drill-down if user requests it ──────────
    # Detect if the user is asking for more analysis vs. just approving.
    # Keywords that signal a drill-down request rather than simple approval.
    ANALYSIS_KEYWORDS = [
        "drill", "deep", "dive", "filter", "segment", "break down", "breakdown",
        "analyse", "analyze", "focus on", "look into", "investigate", "explore",
        "why", "detail", "more on", "expand", "further", "specifically",
    ]
    is_analysis_request = bool(user_input2) and any(
        kw in user_input2.lower() for kw in ANALYSIS_KEYWORDS
    )

    if is_analysis_request:
        emit("round", {"round": 4, "label": "Additional Deep-Dive", "agent": "analyst"})
        emit("status", {"text": "Routing back to Analyst for deeper analysis…"})

        additional_analysis = await run_until_complete(
            analyst,
            task=(
                f"The user has reviewed your analysis of {current_period} and has a follow-up request:\n\n"
                f"USER REQUEST: {user_input2}\n\n"
                f"Here is the full prior analysis for context:\n{analyst_output}\n\n"
                "Run the relevant tool(s) to address this request specifically. "
                "Show results clearly and write Key Findings for this drill-down. "
                "End with exactly: ANALYSIS COMPLETE"
            ),
            trigger="ANALYSIS COMPLETE",
            token=token,
            label="analyst",
            emit=emit,
        )

        # Combine original + new analysis, re-run Master narrative
        emit("round", {"round": 4, "label": "Updated Narrative", "agent": "master"})
        combined_analysis = (
            f"ORIGINAL ANALYSIS:\n{analyst_output}\n\n"
            f"ADDITIONAL DRILL-DOWN (per user request: '{user_input2}'):\n{additional_analysis}"
        )

        master_r4b = await master.run(
            task=(
                f"The analyst has produced an updated analysis incorporating the user's follow-up request.\n\n"
                f"{combined_analysis}\n\n"
                f"EXTERNAL CONTEXT (web research):\n{search_output}\n\n"
                "Write an updated 3-5 sentence executive narrative and a revised slide JSON spec "
                "that reflects both the original findings AND the new drill-down. "
                "End with: NARRATIVE READY — AWAITING YOUR APPROVAL"
            ),
            cancellation_token=token,
        )
        master_output4 = get_text(master_r4b)
        emit("message", {"agent": "master", "content": master_output4})

    # ── Round 5: Visualization ────────────────────────────────
    emit("round", {"round": 5, "label": "Slide Generation", "agent": "viz"})

    ref_str = tools.REFERENCE_DATE.strftime("%Y%m")
    viz_output = await run_until_complete(
        visualization,
        task=(
            f"Generate a PowerPoint slide using this spec:\n\n"
            f"{master_output4}\n\n"
            f"Use output filename: analytics_{ref_str}.pptx\n"
            "End with: VISUALIZATION COMPLETE"
        ),
        trigger="VISUALIZATION COMPLETE",
        token=token,
        label="viz",
        emit=emit,
    )

    emit("slide_ready", {
        "filename":  f"analytics_{ref_str}.pptx",
        "narrative": master_output4,
    })


# Allow running pipeline standalone (terminal mode) for testing
if __name__ == "__main__":

    def terminal_emit(event_type, data):
        if event_type == "message":
            agent = data.get("agent", "?").upper()
            print(f"\n[{agent}]\n{data.get('content', '')}")
        elif event_type == "checkpoint":
            print(f"\n--- CHECKPOINT {data['id']}: {data['text']} ---")
        elif event_type == "round":
            print(f"\n=== ROUND {data['round']}: {data['label']} ===")

    def terminal_input():
        return input("  Your input (Enter to continue): ").strip()

    asyncio.run(run(terminal_emit, terminal_input))