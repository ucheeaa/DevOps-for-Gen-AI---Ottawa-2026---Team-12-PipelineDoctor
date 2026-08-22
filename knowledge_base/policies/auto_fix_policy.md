# Policy: Auto-Fix vs Human Escalation

## Decision Rules

| Condition | Action |
|-----------|--------|
| estimated_step_count < 4 AND risk = LOW | Auto-fix |
| estimated_step_count < 4 AND risk = MEDIUM | Auto-fix |
| estimated_step_count >= 5 | Escalate |
| risk = HIGH | Escalate |
| risk = CRITICAL | Escalate |
| changed_files includes infra/, terraform/, Dockerfile, Jenkinsfile | Escalate |
| branch = main / master / production | Escalate |
| category = PERMISSION_ERROR | Escalate |
| category = INFRA_ERROR | Escalate |
| category = MISSING_DEPENDENCY AND step_count <= 2 | Auto-fix |

## Step Count Definition
A "step" is one discrete action required to resolve the issue
(e.g. "add boto3 to requirements.txt" = 1 step; "provision secret,
update IAM, redeploy, verify" = 4 steps).

## Override
Users can toggle `REQUIRE_APPROVAL_FOR_PRODUCTION=false` in environment
configuration to allow auto-fixes on the main branch (not recommended
for production systems).

## Audit Trail
All decisions — including auto-fixes — are logged to S3 (results/ prefix)
and visible in the Pipeline Doctor dashboard Results tab.
