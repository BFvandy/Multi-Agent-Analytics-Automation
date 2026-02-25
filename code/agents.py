"""
Agent definitions for the Analyst and Manager.
"""

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient

from prompts import ANALYST_SYSTEM_PROMPT, MANAGER_SYSTEM_PROMPT
from tools import (
    get_schema_info,
    get_overall_monthly_summary,
    get_dimension_decomposition,
    get_rolling_average,
    drill_down_segment,
)


def create_analyst_agent(model_client: OpenAIChatCompletionClient) -> AssistantAgent:
    return AssistantAgent(
        name="Analyst",
        model_client=model_client,
        system_message=ANALYST_SYSTEM_PROMPT,
        tools=[
            get_schema_info,
            get_overall_monthly_summary,
            get_dimension_decomposition,
            get_rolling_average,
            drill_down_segment,
        ],
        reflect_on_tool_use=True,  # agent reasons about tool output before responding
    )


def create_manager_agent(model_client: OpenAIChatCompletionClient) -> AssistantAgent:
    return AssistantAgent(
        name="Manager",
        model_client=model_client,
        system_message=MANAGER_SYSTEM_PROMPT,
        tools=[],  # Manager only critiques, does not run tools
    )
