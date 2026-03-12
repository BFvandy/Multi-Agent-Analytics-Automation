"""
Minimal debug test — run this to check if agents work at all.
"""
import asyncio
import os
from dotenv import load_dotenv
from autogen_agentchat.agents import AssistantAgent
from autogen_core import CancellationToken
from autogen_ext.models.openai import OpenAIChatCompletionClient

load_dotenv()

async def main():
    print("1. Creating model client...")
    model_client = OpenAIChatCompletionClient(
        model="gpt-4o",
        api_key=os.environ.get("OPENAI_API_KEY"),
    )

    print("2. Creating agent...")
    agent = AssistantAgent(
        name="Test",
        model_client=model_client,
        system_message="You are a helpful assistant.",
    )

    print("3. Running agent...")
    token = CancellationToken()
    resp = await agent.run(task="Say hello in one sentence.", cancellation_token=token)

    print(f"4. Got response with {len(resp.messages)} messages")
    for i, msg in enumerate(resp.messages):
        content = getattr(msg, "content", None)
        print(f"   msg[{i}]: type={type(msg).__name__}, content_type={type(content).__name__}")
        if isinstance(content, str):
            print(f"   content: {content[:300]}")

if __name__ == "__main__":
    asyncio.run(main())