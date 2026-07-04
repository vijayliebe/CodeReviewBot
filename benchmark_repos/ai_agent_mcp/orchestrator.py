"""AI-agent repo with MCP server — tests MCP-related review checks."""
import os
from google.adk.agents.llm_agent import Agent

OPENAI_API_KEY = "sk-proj-hardcoded-openai-key-abcdefghij"

orchestrator = Agent(
    name="mcp_orchestrator",
    model="gemini-2.5-flash",
    instruction="You are an MCP-backed orchestrator.",
)


def list_files(pattern: str) -> str:
    import subprocess
    # VIOLATION (agent-unsandboxed-shell): shell=True with user-supplied pattern
    return subprocess.run(f"ls {pattern}", shell=True, capture_output=True).stdout
