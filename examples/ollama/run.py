"""Ollama vision-model example: run a task with a local model.

Requires Ollama running locally with a vision-capable model pulled, e.g.::

    ollama pull qwen3-vl
"""

import asyncio

from vlmux import VLMux


async def main() -> None:
    agent = VLMux(model="ollama/qwen3-vl")
    result = await agent.run("Open Calculator and calculate 23 * 47")
    print(result.status, result.message)


if __name__ == "__main__":
    asyncio.run(main())
