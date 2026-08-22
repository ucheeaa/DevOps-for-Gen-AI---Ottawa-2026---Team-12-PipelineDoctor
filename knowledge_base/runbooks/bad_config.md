# Runbook: Missing Environment Variable / Secret at Deploy Time

## Symptom
Pipeline fails at DEPLOY stage with:
```
KeyError: 'DATABASE_URL'
KeyError: 'API_KEY'
KeyError: '<ENV_VAR_NAME>'
```

## Root Cause
A required environment variable or secret is not set in the deployment
environment. Common causes:
- A new secret was added to the code but not added to the deployment
  environment (AWS Secrets Manager, GitHub Actions secrets, Kubernetes secrets).
- The variable was renamed in code but the deployment config still uses
  the old name.
- The variable exists in staging but was not propagated to production.

## Risk Classification
**HIGH** — Deploy-time secret configuration changes touch production
infrastructure. **Human approval always required.**

## Resolution Steps (Require Human Action)
1. Identify the missing variable name from the KeyError.
2. Check if the secret exists in AWS Secrets Manager:
   `aws secretsmanager list-secrets --region us-east-1`
3. If the secret does not exist, create it:
   `aws secretsmanager create-secret --name <name> --secret-string <value>`
4. If the secret exists, ensure the Lambda/ECS task IAM role has
   `secretsmanager:GetSecretValue` permission.
5. Update the deployment configuration to inject the secret as an
   environment variable.
6. Re-run the pipeline.

## Why This Cannot Be Auto-Fixed
Secrets and configuration values are environment-specific. Automatically
setting a secret value would require either a hardcoded value (security
risk) or an assumption about the correct value (correctness risk).
A human must determine the correct secret value and provision it.

## Prevention
- Use infrastructure-as-code to define all required secrets and env vars
  alongside the application code.
- Add a "config validation" step at the START of the deploy stage that
  checks for all required variables before attempting deployment.
