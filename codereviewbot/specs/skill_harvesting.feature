Feature: Skill Harvesting — turning observed patterns into durable rules
  As a tech lead
  I want the agent to surface dominant codebase conventions as candidate rules
  And approve the ones worth keeping without re-deriving them on every review
  So that procedural memory accumulates over time without manual YAML authoring.

  Scenario: Harvesting a dominant snake_case convention
    Given the indexed style summary reports 9 of 10 functions are snake_case
    When the developer runs `codereviewbot harvest-rules --path <repo>`
    Then the CLI prints a suggestion: `style-py-snake-case`
    And the suggestion is NOT yet persisted to rules.yaml

  Scenario: Approving a harvested rule
    Given the developer has reviewed the suggestion `style-py-snake-case`
    When the developer runs `codereviewbot harvest-rules --apply`
    Then the rule is appended to `.crb/rules.yaml` under `custom_rules`
    And future reviews evaluate the rule in the local static pre-pass
    And no LLM call is required to enforce the rule

  Scenario: Manually approving a single rule with a valid regex
    When the developer runs `codereviewbot approve-rule --id no-float-for-money --pattern "float\s*\(" --description "Do not use float for money" --severity high --files "**/billing*.py"`
    Then the regex compiles successfully
    And the rule is written to the repo's `.crb/rules.yaml`
    And the file reports 1 total rule

  Scenario: Rejecting an invalid regex at approve time
    When the developer runs `codereviewbot approve-rule --id bad --pattern "[unclosed" --description "x"`
    Then the CLI exits with a non-zero status
    And no rule is written to disk

  Scenario: No dominant convention means nothing is harvested
    Given the indexed style summary reports 40% snake_case and 40% camelCase functions
    When the developer runs `codereviewbot harvest-rules`
    Then the CLI prints "No dominant style conventions found"
    And no rule is written
