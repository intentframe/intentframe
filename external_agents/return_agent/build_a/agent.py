"""
Build A return-support agent.

A minimal DIY baseline: one hardened LLM reads the assembled chat context and
returns a structured decision. No IntentFrame, no tools, no external enforcement.
"""

from __future__ import annotations

import asyncio
import os
import sys

from agents import Agent, Runner

from real_world_user_prompt import BOUNDARY, USER_PROMPT
from system_prompt import SYSTEM_PROMPT

DEFAULT_MODEL = "gpt-5-mini-2025-08-07"


def build_system_prompt() -> str:
    return SYSTEM_PROMPT.replace("{boundary}", BOUNDARY)


class BuildAReturnAgent:
    def __init__(self, model: str = DEFAULT_MODEL, verbose: bool = True):
        self.model = model
        self.verbose = verbose
        self._agent = Agent(
            name="Build A Return Support Agent",
            instructions=build_system_prompt(),
            model=self.model,
        )

    async def run_async(self, user_prompt: str = USER_PROMPT) -> str:
        result = await Runner.run(
            self._agent,
            user_prompt,
            max_turns=1,
        )
        return result.final_output

    def run(self, user_prompt: str = USER_PROMPT) -> str:
        output = asyncio.run(self.run_async(user_prompt))
        if self.verbose:
            print(output)
        return output


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1

    print("=" * 79)
    print("  BUILD A RETURN AGENT (hardened DIY baseline)")
    print("=" * 79)
    print(f"  Model: {DEFAULT_MODEL}")
    print(f"  Boundary: {BOUNDARY}")
    print()

    agent = BuildAReturnAgent(verbose=True)
    agent.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
