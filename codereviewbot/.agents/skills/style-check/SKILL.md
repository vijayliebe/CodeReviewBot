---
name: style-check
description: Verifies new code conventions against existing codebase structure, naming styles, logging, and error patterns using CodeMemory.
---

# Skill: Style & Convention Check

## Instructions
When auditing code style:
1. Retrieve the codebase style metrics using `get_style_profile`.
2. For new classes and functions, search for similar implementations using `search_similar_code` to align structure, error patterns, and logging.
3. Enforce the dominant naming convention (e.g., snake_case, camelCase).
4. Verify docstring formats and docstring coverage.
5. Check if error handling conforms to standard project practices (avoid bare exceptions).

## Output Format
All findings must be presented under the header `🎨 STYLE FINDINGS` in the following format:
* **File**: `path/to/file:line_num`
  * *Finding*: Naming convention or formatting mismatch.
  * *Dominant Pattern*: The pattern detected across the rest of the codebase.
  * *Suggestion*: Actionable correction.
