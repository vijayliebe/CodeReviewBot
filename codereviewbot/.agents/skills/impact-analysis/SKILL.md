---
name: impact-analysis
description: Analyzes codebase blast radius and checks for integration breaks in cache, databases, queues, and API contracts.
---

# Skill: Impact & Integration Analysis

## Instructions
When analyzing change impact:
1. Identify all references to modified functions or classes using `find_references` to map dependencies.
2. Build the dependency chain using `get_dependency_graph`.
3. Check integration layers specifically:
   - **Cache (Redis)**: Rename of cache keys, TTL updates, caching bypasses.
   - **Queue (Bull)**: Payload structure changes, consumer contract breaks.
   - **Database (PostgreSQL)**: Missing indexes, N+1 queries, schema changes without migrations.
   - **API Contracts**: REST/GraphQL signature breaks.

## Output Format
All findings must be presented under the header `💥 IMPACT & INTEGRATION FINDINGS` in the following format:
* **[SEVERITY]** Layer: `Cache | Queue | Database | API | Code References`
  * *Description*: Details of the blast radius or breaking change.
  * *Files Affected*: Dependent files.
  * *Suggestion*: Mitigation strategy.
