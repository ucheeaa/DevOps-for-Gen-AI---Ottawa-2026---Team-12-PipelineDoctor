# Pipeline Doctor

AI-powered CI/CD pipeline failure diagnosis and auto-fix agent. When code breaks a build, Pipeline Doctor reads the logs, diagnoses the root cause using Amazon Bedrock (Claude Sonnet), and either auto-fixes simple problems or escalates complex ones to a human via the dashboard and Slack.

## Quick Start (Step by Step)

### 1. Clone the repo
```bash
git clone https://github.com/ucheeaa/Pipeline-Doctor.git
cd Pipeline-Doctor
```

### 2. Make sure you have the prerequisites installed
- Python 3.11-3.13 (`python3 --version` to check, `brew install python@3.13` if missing)
- Node.js 18+ (`node --version` to check, `brew install node` if missing)
- AWS CLI v2 (`aws --version` to check, `brew install awscli` if missing)

### 3. Authenticate with AWS

**If you are the account owner (Uchenna):**
```bash
aws login
```

**If you are a teammate using shared credentials:**
```bash
aws configure
```
It will ask for:
- **AWS Access Key ID**: (the access key Uchenna shared with you)
- **AWS Secret Access Key**: (the secret key Uchenna shared with you)
- **Default region name**: `us-east-1`
- **Default output format**: `json`

**Verify it worked (everyone):**
```bash
aws sts get-caller-identity
```
You should see the account ID `714665049802`. If it says "expired" or "no credentials":
- Account owner: re-run `aws login`
- Teammates: re-run `aws configure` and double-check the keys

### 4. Make sure Bedrock Claude is enabled
Go to AWS Console > Amazon Bedrock > Model access (us-east-1 region) and make sure Claude Sonnet is enabled. If not, click "Manage model access" and enable it.

### 5. Run the setup script
```bash
chmod +x setup.sh && ./setup.sh
```
This creates the Python virtual environment, installs all dependencies, and installs the frontend.

### 6. Start the backend (Terminal 1)
```bash
source .venv/bin/activate && python3 -m uvicorn backend.app:app --port 8000 --reload
```
You should see: `Uvicorn running on http://0.0.0.0:8000`

### 7. Start the frontend (Terminal 2 - separate terminal)
```bash
cd frontend && npm run dev
```
You should see: `Local: http://localhost:3000/`

### 8. Open the dashboard
Go to **http://localhost:3000** in your browser.

### 9. Test it
Click any of the scenario buttons in the **Demo Panel** at the top of the dashboard. The `missing_dep` scenario is the best one to start with — it calls Bedrock to diagnose a missing boto3 dependency and proposes a fix.

### Troubleshooting
- **Dark blue screen / nothing renders**: Open browser console (Cmd+Option+J) and check for errors. Try hard refresh (Cmd+Shift+R).
- **AWS expired session / credential errors**: Run `aws configure` again with the shared team credentials.
- **`botocore.exceptions.NoCredentialsError`**: You haven't run `aws configure` yet, or the keys are wrong.
- **`ModuleNotFoundError` when starting backend**: Make sure you ran `source .venv/bin/activate` first.
- **Port already in use**: Kill the old process with `lsof -ti:8000 | xargs kill` or use a different port.
- **Bedrock `AccessDeniedException`**: Bedrock model access isn't enabled. Go to AWS Console > Bedrock > Model access in us-east-1 and enable Claude Sonnet.

## Prerequisites

| Requirement | Install |
|---|---|
| Python 3.11-3.13 | `brew install python@3.13` |
| Node.js 18+ | `brew install node` |
| AWS CLI v2 | `brew install awscli` |
| AWS credentials | `aws login` (then verify: `aws sts get-caller-identity`) |
| Bedrock access | Enable Claude Sonnet in us-east-1 via AWS Console |

## How It Works

```
Developer pushes code
        |
GitHub Actions / Jenkins runs build & tests
        |
   FAIL / RISKY PASS
        |
   Logs land in S3
        |
   Lambda triggers Pipeline Doctor
        |
   +---------------------------+
   |     Pipeline Doctor       |
   |                           |
   |  1. Parse failure         |
   |  2. RAG: search runbooks  |
   |  3. AI: diagnose root     |
   |     cause (Bedrock)       |
   |  4. Generate fix          |
   |  5. Policy: auto-fix or   |
   |     escalate?             |
   +---------------------------+
        |               |
   Auto-fix          Escalate
   (open PR)         (Dashboard + Slack)
```

## Policy Engine Rules

| Condition | Decision |
|---|---|
| Fix < 4 steps AND low/medium risk | Auto-fix |
| Fix >= 5 steps | Escalate to human |
| HIGH or CRITICAL risk | Escalate to human |
| Touches infra/, terraform/, Dockerfile | Escalate |
| Branch is main/master/production | Escalate (configurable) |

## The 6 Demo Scenarios

These match the [Dummy Pipeline](https://github.com/sanyapeter/Dummy_Pipeline) test repo:

| Scenario | Stage | What Happens |
|---|---|---|
| `missing_dep` | BUILD | Missing boto3 - agent proposes adding to requirements.txt |
| `failing_test` | TEST | AssertionError - escalates (could be real regression) |
| `bad_config` | DEPLOY | Missing DATABASE_URL - escalates (secret needed) |
| `slow_deploy` | DEPLOY | Health check timeout - escalates |
| `risky_iam_change` | DEPLOY (pass) | Wildcard IAM detected - always escalates |
| `clean_pass` | - | No issues, logs and moves on |

## Project Structure

```
agent/                     Core agent (your focus area)
  pipeline_doctor.py       Main orchestration loop
  log_analyzer.py          Parse & categorize CI/CD failures
  policy_engine.py         Auto-fix vs escalate decision logic
  rag_retriever.py         Bedrock Knowledge Base queries
  fix_applicator.py        Commit fixes via GitHub API (PRs)
  notifier.py              Slack notifications
  models.py                Shared data models

lambda/                    AWS Lambda handler
  s3_trigger.py            S3 event + API Gateway -> agent

backend/                   FastAPI REST API
  app.py                   Dashboard backend + event processing

frontend/                  React (Vite) dashboard
  src/App.jsx              Main app with 3 tabs
  src/components/
    DemoPanel.jsx          One-click scenario triggers
    ObservabilityTab.jsx   Agent action trace (transparency)
    ApprovalsTab.jsx       Human-in-the-loop approval/deny
    ResultsTab.jsx         Historical results table
    StatsBar.jsx           Live stats counters

infra/                     AWS CDK (deploy later)
  pipeline_doctor_stack.py S3 + Lambda + API Gateway + IAM

knowledge_base/            RAG documents (upload to S3 for KB)
  runbooks/                One runbook per failure scenario
  policies/                Auto-fix policy definition
```

## Configuration

Copy `.env.example` to `.env` and fill in:

```bash
# Required for AI diagnosis
AWS_REGION=us-east-1

# Required for auto-fix (opening PRs)
GITHUB_TOKEN=<your-github-pat-with-repo-scope>
GITHUB_REPO_OWNER=sanyapeter
GITHUB_REPO_NAME=Dummy_Pipeline

# Optional - Slack notifications
SLACK_WEBHOOK_URL=<your-slack-webhook>

# Optional - RAG (set after creating Bedrock Knowledge Base)
BEDROCK_KB_ID=<your-kb-id>

# Policy thresholds (defaults work fine)
AUTO_FIX_MAX_STEPS=4
ESCALATE_STEPS_THRESHOLD=5
REQUIRE_APPROVAL_FOR_PRODUCTION=true
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/pipeline-event` | Submit a pipeline event for processing |
| GET | `/api/events` | List all processed events |
| GET | `/api/events/{id}` | Get event detail + action trace |
| GET | `/api/approvals` | List pending human approvals |
| POST | `/api/approvals/{fix_id}/approve` | Approve a fix |
| POST | `/api/approvals/{fix_id}/deny` | Deny a fix |
| GET | `/api/stats` | Dashboard summary stats |
| GET | `/health` | Health check |

## Testing Without AWS

You can test the frontend + backend flow without Bedrock by POSTing a pre-processed result:

```bash
curl -X POST http://localhost:8000/api/events \
  -H "Content-Type: application/json" \
  -d '{"event": {"event_id": "test-1", "pipeline_id": "99", "status": "FAILED", "stage": "BUILD", "error": "test error", "source": "test"}, "result": {"event_id": "test-1", "status": "auto_fixed", "message": "Fixed it", "fix_status": "applied", "fix": null, "actions": [{"action": "received_event", "timestamp": "2026-01-01T00:00:00"}]}}'
```

## Next Steps (TODO)

- [ ] Deploy to AWS with CDK (`cd infra && cdk deploy`)
- [ ] Create Bedrock Knowledge Base and set BEDROCK_KB_ID
- [ ] Set up Slack webhook for notifications
- [ ] Connect to the live Dummy Pipeline (set GitHub Actions secrets)
- [ ] AgentCore deployment (for production hosting)

## Tech Stack

- **AI**: Amazon Bedrock (Claude Sonnet 4.6)
- **RAG**: Bedrock Knowledge Base
- **Backend**: Python, FastAPI, boto3
- **Frontend**: React + Vite
- **Infra**: AWS CDK (S3, Lambda, API Gateway)
- **CI/CD**: GitHub Actions / Jenkins
- **Notifications**: Slack

