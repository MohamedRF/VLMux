"""OpenRouter example: run a task with a hosted vision model.

Requires ``VLMUX_API_KEY`` (or a saved credential) and a vision-capable model::

    python examples/openrouter/run.py
"""

import asyncio

from vlmux import VLMux


async def main() -> None:
    agent = VLMux(model="openrouter/google/gemini-2.5-pro")
    result = await agent.run("Open Chrome and visit https://github.com")
    print(result.status, result.message)


if __name__ == "__main__":
    asyncio.run(main())
