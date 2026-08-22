# Runbook: Test Failure (AssertionError)

## Symptom
Pipeline fails at TEST stage with:
```
AssertionError: assert <actual> == <expected>
FAILED tests/test_app.py::<TestName>
```

## Root Cause
A unit test is asserting a value that no longer matches the code's output.
This could be:
- A genuine regression introduced by the triggering commit.
- An intentionally wrong expected value (e.g. a test written to fail for demo/TDD purposes).
- A flaky test that depends on external state.

## Risk Classification
**MEDIUM-HIGH** — Test failures may indicate a real regression. Auto-fixing
the test assertion itself (to match the new behavior) risks masking a bug.
**Human review is required.**

## Investigation Steps
1. Read the full assertion error to understand expected vs actual values.
2. Check the commit diff (`changed_files`) — did the commit modify the
   function being tested?
3. If the function logic changed intentionally, update the test to match.
4. If the function should not have changed, revert the offending commit.
5. Check for flakiness: re-run the test in isolation.

## Escalation Criteria
- If the test touches business logic, authentication, or data transformation:
  **escalate to the developer who made the commit**.
- If the change is clearly intentional (e.g. a refactor), the developer
  should update the test themselves.

## Never Auto-Fix
Do not auto-correct assertion values without human review. A failing test
is a signal, not just noise.
