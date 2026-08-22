# Runbook: Missing Python Dependency (ModuleNotFoundError)

## Symptom
Pipeline fails at BUILD or INSTALL stage with:
```
ModuleNotFoundError: No module named '<package_name>'
```
Example: `ModuleNotFoundError: No module named 'boto3'`

## Root Cause
A required Python package is not listed in `requirements.txt`, or the
`requirements.txt` was modified and the missing package was accidentally
removed during a recent commit.

## Risk Classification
**LOW** — Adding a pinned dependency to requirements.txt is a safe, reversible
change with no production impact.

## Auto-Fix Procedure (< 4 steps)
1. Identify the missing package name from the error message.
2. Check PyPI for the current stable version: `pip index versions <package>`.
3. Add the pinned dependency to `requirements.txt` (e.g. `boto3==1.38.0`).
4. Commit the change to a new fix branch and open a pull request.

## Example Fix
```diff
# requirements.txt
 flask==3.0.0
+boto3==1.38.0
 pytest==8.3.0
```

## Verification
Re-run the pipeline. The BUILD stage should now pass the import check.

## Prevention
- Pin all dependencies with exact versions (`==`) to prevent version drift.
- Run `pip check` in CI to catch dependency conflicts early.
- Use `pip-compile` (pip-tools) to keep requirements.txt in sync with
  requirements.in.
