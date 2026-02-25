import asyncio
import os
from dotenv import load_dotenv
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_ext.models.openai import OpenAIChatCompletionClient

load_dotenv()

async def main():
    model_client = OpenAIChatCompletionClient(
        model="gpt-4o",
        api_key=os.environ.get("OPENAI_API_KEY"),
    )

    agent = AssistantAgent(
        name="TestAgent",
        model_client=model_client,
        system_message="You are a helpful assistant. Keep responses short.",
    )

    team = RoundRobinGroupChat(
        participants=[agent],
        termination_condition=MaxMessageTermination(2),
    )

    async for message in team.run_stream(task="Say hello and confirm you are working."):
        if hasattr(message, "source"):
            print(f"[{message.source}]: {message.content}")

asyncio.run(main())