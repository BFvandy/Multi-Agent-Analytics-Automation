"""
Agent definitions for the multi-agent analytics system.
"""

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient

from prompts_multi import (
    MASTER_SYSTEM_PROMPT,
    ANALYST_MULTI_SYSTEM_PROMPT,
    WEBSEARCH_SYSTEM_PROMPT,
    VISUALIZATION_SYSTEM_PROMPT,
)
from tools import (
    get_schema_info,
    get_overall_monthly_summary,
    get_dimension_decomposition,
    get_segment_decomposition,
    drill_down_segment,
    web_search,
    generate_slide,
)


def create_master_agent(model_client: OpenAIChatCompletionClient) -> AssistantAgent:
    return AssistantAgent(
        name="Master",
        model_client=model_client,
        system_message=MASTER_SYSTEM_PROMPT,
        tools=[],  # Master only orchestrates — no tools
    )


def create_analyst_agent_multi(model_client: OpenAIChatCompletionClient) -> AssistantAgent:
    return AssistantAgent(
        name="Analyst",
        model_client=model_client,
        system_message=ANALYST_MULTI_SYSTEM_PROMPT,
        tools=[
            get_schema_info,
            get_overall_monthly_summary,
            get_dimension_decomposition,
            get_trend_charts,
            get_segment_decomposition,
            drill_down_segment,
        ],
        reflect_on_tool_use=True,
    )


def create_websearch_agent(model_client: OpenAIChatCompletionClient) -> AssistantAgent:
    return AssistantAgent(
        name="WebSearch",
        model_client=model_client,
        system_message=WEBSEARCH_SYSTEM_PROMPT,
        tools=[web_search],
        reflect_on_tool_use=True,
    )


def create_visualization_agent(model_client: OpenAIChatCompletionClient) -> AssistantAgent:
    return AssistantAgent(
        name="Visualization",
        model_client=model_client,
        system_message=VISUALIZATION_SYSTEM_PROMPT,
        tools=[generate_slide],
        reflect_on_tool_use=True,
    )