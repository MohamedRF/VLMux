"""MCP example: direct computer control without a model.

The MCP server exposes the same tools over stdio::

    vlmux mcp
    vlmux-mcp
"""

import asyncio

from vlmux import Computer


async def main() -> None:
    computer = Computer()
    await computer.open_app("calculator")
    await computer.wait(500)
    await computer.type("2*2")
    await computer.hotkey(["enter"])


if __name__ == "__main__":
    asyncio.run(main())
