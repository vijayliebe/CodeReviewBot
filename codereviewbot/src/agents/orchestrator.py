from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.agents.parallel_agent import ParallelAgent
from google.adk.agents.llm_agent import Agent

# Import tools and instructions
from src.mcp_servers.filesystem_mcp_server import list_directory, read_file
from src.mcp_servers.github_mcp_server import get_pr_diff, get_pr_files, get_commit_diff
from src.agents.profiler_agent import PROFILER_INSTRUCTION
from src.agents.security_auditor import verify_package_exists, SECURITY_INSTRUCTION
from src.agents.style_checker import STYLE_INSTRUCTION
from src.agents.impact_analyzer import IMPACT_INSTRUCTION
from src.agents.business_rules_checker import check_custom_rules, RULES_INSTRUCTION
from src.agents.summary_generator import SUMMARY_INSTRUCTION

# Import CodeMemory tools
from src.mcp_servers.code_memory_mcp_server import (
    search_similar_code,
    get_style_profile,
    find_references,
    get_dependency_graph,
    get_pattern_frequency
)
from src.mcp_servers.filesystem_mcp_server import search_files

# 1. Instantiate agents locally to prevent Pydantic double-parenting validation errors
profiler_agent = Agent(
    name="profiler_agent",
    model="gemini-2.5-flash",
    description="Analyzes the PR diff and profiles the repository language, architecture, and integration layers.",
    instruction=PROFILER_INSTRUCTION,
    tools=[get_pr_diff, get_pr_files, get_commit_diff, list_directory, read_file]
)

security_auditor = Agent(
    name="security_auditor",
    model="gemini-2.5-flash",
    description="Scans code changes for hardcoded secrets, SQL injection, XSS, and hallucinated packages.",
    instruction=SECURITY_INSTRUCTION,
    tools=[verify_package_exists, read_file]
)

style_checker = Agent(
    name="style_checker",
    model="gemini-2.5-flash",
    description="Compares new code changes against existing codebase style and formatting conventions using CodeMemory.",
    instruction=STYLE_INSTRUCTION,
    tools=[search_similar_code, get_style_profile, read_file]
)

impact_analyzer = Agent(
    name="impact_analyzer",
    model="gemini-2.5-flash",
    description="Analyzes code blast radius and flags database query issues, queue payload mismatches, and cache key changes.",
    instruction=IMPACT_INSTRUCTION,
    tools=[find_references, get_dependency_graph, search_files, read_file]
)

business_rules_checker = Agent(
    name="business_rules_checker",
    model="gemini-2.5-flash",
    description="Validates code against repo-specific rules.yaml, inline annotations, and auto-discovered patterns.",
    instruction=RULES_INSTRUCTION,
    tools=[check_custom_rules, get_pattern_frequency, read_file, search_files]
)

summary_generator = Agent(
    name="summary_generator",
    model="gemini-2.5-flash",
    description="Aggregates and formats the final CodeReviewBot report.",
    instruction=SUMMARY_INSTRUCTION
)

# 2. Combine analysis agents into a parallel block
analysis_parallel = ParallelAgent(
    name="analysis_parallel",
    description="Executes Security, Style, Impact, and Business Rules checks in parallel.",
    sub_agents=[security_auditor, style_checker, impact_analyzer, business_rules_checker]
)

# 3. Define the root orchestrator agent sequentially
root_agent = SequentialAgent(
    name="root_agent",
    description="Main orchestrator that profiles the repository, runs concurrent audits, and compiles the final report.",
    sub_agents=[profiler_agent, analysis_parallel, summary_generator]
)
