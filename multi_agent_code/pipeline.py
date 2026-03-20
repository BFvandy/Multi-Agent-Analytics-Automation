"""
pipeline.py — the actual multi-agent logic, decoupled from both
terminal printing and the Flask server.

emit(event_type, data)  → sends an event to whoever is listening
wait_for_input()        → blocks until the user responds
"""

import asyncio
import json as _json
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

    tools.init(reference_date)   # reads DATASET_PRESET from .env automatically

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

    # ── Round 1a-i: Step 1 — Schema ──────────────────────────────────────────
    emit("round", {"round": 1, "label": "Step 1 — Schema & Periods", "agent": "analyst"})
    step1_output = await run_until_complete(
        analyst,
        task=(
            f"Call get_schema_info for the credit card dataset. "
            f"Reference date is {tools.REFERENCE_DATE.strftime('%B %d, %Y')}, analysing {current_period}. "
            "Report the date range, row count, columns, card types, exp types, and analysis periods. "
            "End with exactly: STEP 1 COMPLETE"
        ),
        trigger="STEP 1 COMPLETE",
        token=token,
        label="analyst",
        emit=emit,
        max_attempts=3,
    )

    # ── Round 1a-ii: Step 2 — Monthly Summary ────────────────────────────────
    emit("round", {"round": 1, "label": "Step 2 — Monthly Summary", "agent": "analyst"})
    step2_output = await run_until_complete(
        analyst,
        task=(
            f"Call get_overall_monthly_summary for {current_period}. "
            "Report total spend, MoM change, YoY change, and transaction volume. "
            "End with exactly: STEP 2 COMPLETE"
        ),
        trigger="STEP 2 COMPLETE",
        token=token,
        label="analyst",
        emit=emit,
        max_attempts=3,
    )

    # ── Round 1a-iii: Step 3 — CTG Decomposition ─────────────────────────────
    emit("round", {"round": 1, "label": "Step 3 — CTG Decomposition", "agent": "analyst"})
    cfg      = tools.DATASET_CONFIG
    dim_list = " then ".join(f"'{d}'" for d in cfg.dimensions)
    step3_output = await run_until_complete(
        analyst,
        task=(
            f"Call get_dimension_decomposition for {dim_list}. "
            f"The value column is '{cfg.value_col}' ({cfg.value_label}). "
            f"For each dimension, present a table: Segment | {cfg.value_label} Current | {cfg.value_label} Prior Year | YoY % | CTG %. "
            f"After all tables state: TOP {cfg.primary_dim.upper()} DRIVER: [name] (CTG: X%, YoY: X%). "
            "End with exactly: STEP 3 COMPLETE"
        ),
        trigger="STEP 3 COMPLETE",
        token=token,
        label="analyst",
        emit=emit,
        max_attempts=3,
    )

    analyst_steps123 = "\n\n".join([step1_output, step2_output, step3_output])

    # ── Emit trend charts directly from pipeline ──────────────────────────────
    emit("round", {"round": 1, "label": "12-Month Trend Charts", "agent": "analyst"})
    emit("status", {"text": "Generating 12-month trend charts…"})
    for dimension in tools.DATASET_CONFIG.dimensions:
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
            f"Now run Step 4: identify the top '{cfg.primary_dim}' driver from your Step 3 output above, "
            f"then call `get_segment_decomposition` passing that exact value as `primary_segment_value`. "
            f"This will show '{cfg.secondary_dim}' breakdown within that {cfg.primary_dim} segment. "
            f"Present the full breakdown table: {cfg.secondary_dim} | {cfg.value_label} Current | {cfg.value_label} Prior Year | YoY % | CTG (within segment) | CTG (portfolio). "
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

    # ── Checkpoint 1 feedback loop ────────────────────────────
    # Master reads user input, routes to the right agent if needed,
    # and loops until the user approves.
    checkpoint1_context = analyst_output
    while True:
        emit("checkpoint", {
            "id":   1,
            "text": "Review the analysis above. Type a question, request more analysis, or press Continue to proceed.",
        })
        user_input = await wait_for_input() if asyncio.iscoroutinefunction(wait_for_input) else wait_for_input()
        emit("user_message", {"content": user_input or "Looks good, continue."})

        # Blank / approval → break out of loop
        APPROVAL = {"", "ok", "continue", "looks good", "proceed", "yes", "approve", "approved"}
        if user_input.strip().lower() in APPROVAL:
            break

        # Master decides what to do with the feedback
        emit("round", {"round": 1, "label": "Handling Your Feedback", "agent": "master"})
        master_feedback_resp = await master.run(
            task=(
                f"The user has reviewed the analysis for {current_period} and provided feedback.\n\n"
                f"FULL ANALYSIS SO FAR:\n{checkpoint1_context}\n\n"
                f"USER FEEDBACK: {user_input}\n\n"
                "Decide what action to take:\n"
                "- If it's a question you can answer from the data above, answer it directly.\n"
                "- If it requires more data analysis, write exactly: ROUTE_TO_ANALYST: [specific instruction for analyst]\n"
                "- If it requires web research, write exactly: ROUTE_TO_SEARCH: [specific search queries]\n"
                "After handling it, summarise what you did for the user."
            ),
            cancellation_token=token,
        )
        master_feedback_text = get_text(master_feedback_resp)
        emit("message", {"agent": "master", "content": master_feedback_text})

        # Route to Analyst if needed — use a fresh agent to avoid stale history
        if "ROUTE_TO_ANALYST:" in master_feedback_text:
            instruction = master_feedback_text.split("ROUTE_TO_ANALYST:")[-1].strip().split("\n")[0]
            emit("round", {"round": 1, "label": "Additional Analysis", "agent": "analyst"})
            fresh_analyst = _make_intercepting_analyst(model_client, emit)
            extra = await run_until_complete(
                fresh_analyst,
                task=(
                    f"You are a senior data analyst. The user has requested additional analysis for {current_period}.\n\n"
                    f"INSTRUCTION: {instruction}\n\n"
                    f"AVAILABLE TOOLS: get_dimension_decomposition, get_segment_decomposition, drill_down_segment, get_overall_monthly_summary.\n"
                    f"The value column is '{cfg.value_col}', dimensions are {cfg.dimensions}.\n\n"
                    "Call the most relevant tool(s), show the results clearly in a table, "
                    "and write 2-3 key observations. "
                    "End with exactly: ANALYSIS COMPLETE"
                ),
                trigger="ANALYSIS COMPLETE",
                token=token,
                label="analyst",
                emit=emit,
                max_attempts=4,
            )
            checkpoint1_context += f"\n\nADDITIONAL ANALYSIS (user request: '{user_input}'):\n{extra}"

        # Route to WebSearch if needed
        elif "ROUTE_TO_SEARCH:" in master_feedback_text:
            queries = master_feedback_text.split("ROUTE_TO_SEARCH:")[-1].strip().split("\n")[0]
            emit("round", {"round": 1, "label": "Additional Research", "agent": "search"})
            extra_search = await run_until_complete(
                websearch,
                task=(
                    f"Run the following search queries:\n{queries}\n\n"
                    "Synthesise findings clearly. End with: SEARCH COMPLETE"
                ),
                trigger="SEARCH COMPLETE",
                token=token,
                label="search",
                emit=emit,
            )
            checkpoint1_context += f"\n\nADDITIONAL RESEARCH (user request: '{user_input}'):\n{extra_search}"

        # Loop back to show another checkpoint

    analyst_output = checkpoint1_context

    # ── Round 2: Master search queries ────────────────────────
    emit("round", {"round": 2, "label": "Identifying Search Topics", "agent": "master"})

    master_r2 = await master.run(
        task=(
            f"Here is the Data Analyst's quantitative analysis for {current_period}:\n\n"
            f"{analyst_output}\n\n"
            f"DATASET CONTEXT: value metric = '{cfg.value_col}' ({cfg.value_label}), "
            f"primary dimension = '{cfg.primary_dim}', secondary dimension = '{cfg.secondary_dim}'.\n\n"
            f"Identify the KEY DRIVER (the '{cfg.primary_dim}' segment with the highest absolute CTG, "
            f"and the top '{cfg.secondary_dim}' within it from Step 4). "
            "Write 2-3 specific web search queries to explain WHY this driver performed the way it did. "
            "Use the actual segment names from the analysis. End with: SEARCH QUERIES READY"
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
            f"DATASET CONTEXT: value metric = '{cfg.value_col}' ({cfg.value_label}), "
            f"primary dimension = '{cfg.primary_dim}', secondary dimension = '{cfg.secondary_dim}'. "
            f"Use these exact names throughout — do not substitute with other dataset terminology.\n\n"
            "Write a 3-5 sentence executive narrative combining what happened and why. "
            "Then output the complete slide JSON spec with ALL segments. "
            "End with: NARRATIVE READY — AWAITING YOUR APPROVAL"
        ),
        cancellation_token=token,
    )
    master_output4 = get_text(master_r4)
    emit("message", {"agent": "master", "content": master_output4})

    # ── Checkpoint 2 feedback loop ────────────────────────────
    # Same pattern as checkpoint 1 — Master routes to agents as needed,
    # loops until user approves, then proceeds to visualization.
    checkpoint2_context = {
        "analyst_output": analyst_output,
        "search_output":  search_output,
        "master_output4": master_output4,
    }

    while True:
        emit("checkpoint", {
            "id":   2,
            "text": "Review the narrative and slide spec. Type a question, request changes, or press Continue to generate the slide.",
        })
        user_input2 = await wait_for_input() if asyncio.iscoroutinefunction(wait_for_input) else wait_for_input()
        emit("user_message", {"content": user_input2 or "Looks good, generate the slide."})

        APPROVAL = {"", "ok", "continue", "looks good", "proceed", "yes", "approve", "approved", "generate", "generate the slide"}
        if user_input2.strip().lower() in APPROVAL:
            master_output4 = checkpoint2_context["master_output4"]
            break

        # Master decides what to do
        emit("round", {"round": 4, "label": "Handling Your Feedback", "agent": "master"})
        master_fb2 = await master.run(
            task=(
                f"The user has reviewed the narrative and slide spec and provided feedback.\n\n"
                f"CURRENT NARRATIVE AND SLIDE SPEC:\n{checkpoint2_context['master_output4']}\n\n"
                f"FULL ANALYSIS CONTEXT:\n{checkpoint2_context['analyst_output']}\n\n"
                f"WEB RESEARCH:\n{checkpoint2_context['search_output']}\n\n"
                f"USER FEEDBACK: {user_input2}\n\n"
                "Decide what action to take:\n"
                "- If it's a question you can answer from the context above, answer it directly, then output an updated narrative and slide spec.\n"
                "- If it requires more data analysis, write exactly: ROUTE_TO_ANALYST: [specific instruction]\n"
                "- If it requires web research, write exactly: ROUTE_TO_SEARCH: [specific queries]\n"
                "- If it's an edit to the narrative or slide, apply the edit and output the full updated spec.\n"
                "Always end with the complete updated slide JSON spec and: NARRATIVE READY — AWAITING YOUR APPROVAL"
            ),
            cancellation_token=token,
        )
        master_fb2_text = get_text(master_fb2)

        # Route to Analyst if needed — fresh agent to avoid stale history
        if "ROUTE_TO_ANALYST:" in master_fb2_text:
            instruction = master_fb2_text.split("ROUTE_TO_ANALYST:")[-1].strip().split("\n")[0]
            emit("round", {"round": 4, "label": "Additional Analysis", "agent": "analyst"})
            fresh_analyst2 = _make_intercepting_analyst(model_client, emit)
            extra = await run_until_complete(
                fresh_analyst2,
                task=(
                    f"You are a senior data analyst. The user has requested additional analysis for {current_period}.\n\n"
                    f"INSTRUCTION: {instruction}\n\n"
                    f"AVAILABLE TOOLS: get_dimension_decomposition, get_segment_decomposition, drill_down_segment, get_overall_monthly_summary.\n"
                    f"The value column is '{cfg.value_col}', dimensions are {cfg.dimensions}.\n\n"
                    "Call the most relevant tool(s), show the results clearly in a table, "
                    "and write 2-3 key observations. "
                    "End with exactly: ANALYSIS COMPLETE"
                ),
                trigger="ANALYSIS COMPLETE",
                token=token,
                label="analyst",
                emit=emit,
                max_attempts=4,
            )
            checkpoint2_context["analyst_output"] += f"\n\nADDITIONAL ANALYSIS:\n{extra}"

            # Re-run Master narrative with new data
            emit("round", {"round": 4, "label": "Updated Narrative", "agent": "master"})
            master_updated = await master.run(
                task=(
                    f"Updated analysis available. Revise the narrative and slide spec.\n\n"
                    f"FULL ANALYSIS:\n{checkpoint2_context['analyst_output']}\n\n"
                    f"WEB RESEARCH:\n{checkpoint2_context['search_output']}\n\n"
                    f"USER REQUEST: {user_input2}\n\n"
                    "Output the complete updated narrative and slide JSON spec. "
                    "End with: NARRATIVE READY — AWAITING YOUR APPROVAL"
                ),
                cancellation_token=token,
            )
            master_fb2_text = get_text(master_updated)

        # Route to WebSearch if needed
        elif "ROUTE_TO_SEARCH:" in master_fb2_text:
            queries = master_fb2_text.split("ROUTE_TO_SEARCH:")[-1].strip().split("\n")[0]
            emit("round", {"round": 4, "label": "Additional Research", "agent": "search"})
            extra_search = await run_until_complete(
                websearch,
                task=(
                    f"Run the following search queries:\n{queries}\n\n"
                    "Synthesise findings clearly. End with: SEARCH COMPLETE"
                ),
                trigger="SEARCH COMPLETE",
                token=token,
                label="search",
                emit=emit,
            )
            checkpoint2_context["search_output"] += f"\n\nADDITIONAL RESEARCH:\n{extra_search}"

            # Re-run Master narrative with new search context
            emit("round", {"round": 4, "label": "Updated Narrative", "agent": "master"})
            master_updated = await master.run(
                task=(
                    f"Additional web research available. Revise the narrative and slide spec.\n\n"
                    f"FULL ANALYSIS:\n{checkpoint2_context['analyst_output']}\n\n"
                    f"UPDATED WEB RESEARCH:\n{checkpoint2_context['search_output']}\n\n"
                    f"USER REQUEST: {user_input2}\n\n"
                    "Output the complete updated narrative and slide JSON spec. "
                    "End with: NARRATIVE READY — AWAITING YOUR APPROVAL"
                ),
                cancellation_token=token,
            )
            master_fb2_text = get_text(master_updated)

        emit("message", {"agent": "master", "content": master_fb2_text})
        checkpoint2_context["master_output4"] = master_fb2_text
        # Loop back for another checkpoint

    # ── Round 5: Visualization ─────────────────────────────────
    # Call generate_slide directly from pipeline — bypasses LLM timeout entirely.
    # The viz agent was timing out because node takes >60s with large payloads.
    emit("round", {"round": 5, "label": "Slide Generation", "agent": "viz"})
    emit("status", {"text": "Extracting slide spec from narrative…"})

    ref_str        = tools.REFERENCE_DATE.strftime("%Y%m")
    output_filename = f"analytics_{ref_str}.pptx"

    # Parse the JSON spec out of master_output4
    import re as _re
    slide_result = None
    json_match = _re.search(r'```json\s*(\{.*?\})\s*```', master_output4, _re.DOTALL)
    if json_match:
        try:
            spec = _json.loads(json_match.group(1))
            emit("status", {"text": "Generating PowerPoint slide…"})
            raw = tools.generate_slide(
                title           = spec.get("title", "Analytics Report"),
                subtitle        = spec.get("subtitle", ""),
                bullets         = spec.get("bullets", []),
                chart_title     = spec.get("chart_title", ""),
                chart_data      = spec.get("chart_data", []),
                table_title     = spec.get("table_title", ""),
                table_data      = spec.get("table_data", [[]]),
                footnote        = spec.get("footnote", ""),
                output_filename = output_filename,
            )
            slide_result = _json.loads(raw)
            print(f"[pipeline] generate_slide result: {slide_result}")
        except Exception as e:
            print(f"[pipeline] slide generation error: {e}")
            emit("status", {"text": f"Slide error: {e}"})
    else:
        print("[pipeline] No JSON spec found in master narrative — falling back to viz agent")
        viz_output = await run_until_complete(
            visualization,
            task=(
                f"Generate a PowerPoint slide using this spec:\n\n"
                f"{master_output4}\n\n"
                f"Use output filename: {output_filename}\n"
                "End with: VISUALIZATION COMPLETE"
            ),
            trigger="VISUALIZATION COMPLETE",
            token=token,
            label="viz",
            emit=emit,
            max_attempts=2,
        )

    # Only emit slide_ready if the file actually exists
    from pathlib import Path as _Path
    output_path = _Path(tools._TOOLS_DIR).parent / "output" / output_filename
    if output_path.exists():
        emit("message", {"agent": "viz", "content": f"✅ Slide saved to `output/{output_filename}`"})
        emit("slide_ready", {
            "filename":  output_filename,
            "narrative": master_output4,
        })
    else:
        emit("message", {"agent": "viz", "content": "⚠️ Slide generation failed — file was not created. Check that Node.js and pptxgenjs are installed correctly."})
        emit("status", {"text": "Slide generation failed. Run: cd multi_agent_code && npm install pptxgenjs"})


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