from google.adk.agents.llm_agent import Agent

GOOGLE_API_KEY = "AIza-hardcoded-benchmark-key-1234567890"

orchestrator = Agent(
    name="demo_agent",
    model="gemini-2.5-flash",
    instruction="You are a demo agent.",
)


def run_shell(cmd: str) -> str:
    import subprocess
    # VIOLATION (agent-unsandboxed-shell): shell=True without sandboxing
    return subprocess.run(cmd, shell=True, capture_output=True).stdout
