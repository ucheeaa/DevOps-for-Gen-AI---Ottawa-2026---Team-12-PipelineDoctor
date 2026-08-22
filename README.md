# Pipeline Doctor

**Team 12 - DevOps for GenAI Hackathon 2026 (Ottawa)**

**Theme:** DevOps + Generative AI for CI/CD Automation

AI-powered CI/CD pipeline failure diagnosis and auto-fix agent. When code breaks a build, Pipeline Doctor reads the logs, diagnoses the root cause using Amazon Bedrock (Claude Sonnet), and either auto-fixes simple problems via GitHub PRs or escalates complex ones to a human via a dashboard and Slack notifications.

---

## Elevator Pitch

CI/CD pipelines break daily. Developers waste 30-60 minutes per failure reading cryptic logs, Googling errors, and applying one-line fixes. Pipeline Doctor uses GenAI (Amazon Bedrock Claude) with RAG-augmented runbooks to automatically diagnose failures, generate fixes, and either auto-apply them or escalate to a human, all in under 60 seconds. It reduces mean-time-to-recovery by up to 80% while maintaining human oversight for high-risk changes.

---

## Problem Statement & Target Users

**Problem:** CI/CD pipeline failures are the #1 time sink for DevOps teams. A missing dependency, a typo in config, or a flaky test can block an entire team for 30-60 minutes while someone manually debugs logs.

**Target Users:**
- DevOps engineers managing CI/CD pipelines
- Platform teams responsible for developer productivity
- Development teams using GitHub Actions or Jenkins

**Measurable Outcomes:**
1. Reduce mean-time-to-recovery (MTTR) for pipeline failures from 30+ minutes to under 60 seconds
2. Auto-fix 60-70% of common failures (missing dependencies, lint errors, simple config issues)
3. Escalate 100% of high-risk changes to human review (zero unsafe auto-deployments)
4. Provide full observability trace for every agent decision (auditability)

---

## Architecture

```
Developer pushes code
        |
GitHub Actions / Jenkins runs build & tests
        |
   FAIL / RISKY PASS
        |
   Logs land in S3 (pipeline-doctor-logs-714665049802)
        |
   S3 Event Notification -> Lambda (pipeline-doctor-trigger)
        |                         |
        |            [OR] API Gateway POST /pipeline-event
        |
   +---------------------------------------------------+
   |              Pipeline Doctor Agent                  |
   |                                                    |
   |  1. LogAnalyzer    -> Categorize failure (regex)   |
   |  2. RAGRetriever   -> Query Bedrock KB (runbooks)  |
   |  3. Bedrock Claude -> Diagnose root cause (AI)     |
   |  4. Bedrock Claude -> Generate fix (AI)            |
   |  5. PolicyEngine   -> Auto-fix or escalate?        |
   +---------------------------------------------------+
        |                           |
   Auto-fix (LOW risk)         Escalate (HIGH risk)
   - Create branch              - Slack notification
   - Commit fix                 - Dashboard approval UI
   - Open PR                    - Human approves/denies
   - Trigger CI re-run          - Then apply fix
        |                           |
   +---------------------------------------------------+
   |              FastAPI Backend                        |
   |  - Stores events/results    - Approval workflow    |
   |  - Syncs from S3            - Stats/metrics        |
   +---------------------------------------------------+
        |
   React Dashboard (Vite)
   - Demo panel         - Results history
   - Approval queue     - Observability trace
```

### AWS Services Used

| Service | Purpose |
|---|---|
| Amazon Bedrock (Claude Sonnet 4.6) | AI reasoning - diagnosis and fix generation |
| Bedrock Knowledge Base | RAG retrieval of runbooks and past incidents |
| S3 | Pipeline log storage + processed results |
| Lambda | Serverless agent execution (300s timeout, 1024MB) |
| API Gateway (HTTP API) | REST entry point for direct invocation |
| AWS CDK | Infrastructure as code (reproducible deployment) |
| IAM | Least-privilege roles for Lambda, S3, Bedrock |

---

## Dummy Test repo with pipeline examples
https://github.com/sanyapeter/Dummy_Pipeline

## Quick Start (Step by Step)

### 1. Clone the repo
```bash
git clone https://github.com/ucheeaa/DevOps-for-Gen-AI---Ottawa-2026---Team-12-PipelineDoctor.git
cd DevOps-for-Gen-AI---Ottawa-2026---Team-12-PipelineDoctor
```

### 2. Prerequisites

| Requirement | Install |
|---|---|
| Python 3.11-3.13 | `brew install python@3.13` |
| Node.js 18+ | `brew install node` |
| AWS CLI v2 | `brew install awscli` |
| AWS credentials | `aws configure` (region: us-east-1) |
| Bedrock model access | Enable Claude Sonnet in us-east-1 via AWS Console |

### 3. Authenticate with AWS
```bash
aws configure
# AWS Access Key ID: <your-key>
# AWS Secret Access Key: <your-secret>
# Default region: us-east-1
# Output format: json

# Verify:
aws sts get-caller-identity
```

### 4. Run the setup script
```bash
chmod +x setup.sh && ./setup.sh
```
This creates the Python virtual environment, installs dependencies, and installs the frontend.

### 5. Start the backend (Terminal 1)
```bash
source .venv/bin/activate
python3 -m uvicorn backend.app:app --port 8000 --reload
```

### 6. Start the frontend (Terminal 2)
```bash
cd frontend && npm run dev
```

### 7. Open the dashboard
Navigate to **http://localhost:3000** in your browser.

### 8. Test it
Click any scenario button in the Demo Panel. The `missing_dep` scenario calls Bedrock to diagnose a missing boto3 dependency and proposes a fix.

---

## How It Works - End to End Flow

### Step 1: Trigger
A pipeline fails in GitHub Actions or Jenkins. The failure log is written to S3. An S3 event notification triggers the Lambda function. Alternatively, the dashboard can POST a pipeline event directly via the API.

### Step 2: Log Analysis (`agent/log_analyzer.py`)
The LogAnalyzer uses regex pattern matching to categorize the failure into one of 9 categories: MISSING_DEPENDENCY, TEST_FAILURE, BUILD_ERROR, LINT_ERROR, INFRA_ERROR, PERMISSION_ERROR, NETWORK_ERROR, CONFIGURATION_ERROR, or UNKNOWN. It detects the failed stage and extracts the error message.

### Step 3: RAG Retrieval (`agent/rag_retriever.py`)
The RAGRetriever queries a Bedrock Knowledge Base containing runbooks and historical incident data. It constructs a targeted query like: "How to fix missing_dependency in CI/CD pipeline at stage BUILD. Error: ModuleNotFoundError..." and retrieves up to 5 relevant passages.

### Step 4: AI Diagnosis (`agent/pipeline_doctor.py`)
The agent sends the failure details, changed files, commit SHA, category, and RAG context to Claude via the Bedrock Converse API. Claude returns a structured JSON response with: root cause, confidence score (0.0-1.0), diagnosis steps, and whether it's safe to auto-fix.

### Step 5: Fix Generation
A second Bedrock call asks Claude to generate the minimal fix. Claude returns: description, steps, file changes (filename to new content), PR title, and PR body.

### Step 6: Policy Gate (`agent/policy_engine.py`)
The PolicyEngine evaluates risk based on configurable rules:
- Base risk from failure category (MISSING_DEPENDENCY = LOW, INFRA_ERROR = HIGH)
- Step count: >= 5 steps escalates risk
- Sensitive file paths: `infra/`, `terraform/`, `.github/workflows/`, `Dockerfile`, `migrations/` = HIGH
- Production branches (`main`, `master`, `production`) = HIGH (configurable)
- Too many changed files (> 5) = escalate

### Step 7a: Auto-Fix Path (`agent/fix_applicator.py`)
If policy allows auto-fix:
1. Creates branch `fix/{fix-id}` via GitHub API
2. Commits each file change
3. Opens a pull request with AI-generated title/body
4. Triggers CI re-run via workflow_dispatch

### Step 7b: Escalation Path (`agent/notifier.py`)
If policy requires human approval:
1. Posts Slack notification with Block Kit (approve/deny buttons, root cause, risk level)
2. Registers fix in the backend approval queue
3. Human reviews on dashboard and approves/denies
4. On approval, fix is applied via the same GitHub PR workflow

---

## Policy Engine Rules

| Condition | Decision |
|---|---|
| Fix < 4 steps AND low/medium risk | Auto-fix |
| Fix >= 5 steps | Escalate to human |
| HIGH or CRITICAL risk | Escalate to human |
| Touches `infra/`, `terraform/`, `Dockerfile` | Escalate |
| Touches `.github/workflows/`, `k8s/`, `helm/` | Escalate |
| Branch is `main`/`master`/`production` | Escalate (configurable) |
| More than 5 changed files in commit | Escalate |

---

## Demo Scenarios

These match the [Dummy Pipeline](https://github.com/sanyapeter/Dummy_Pipeline) test repo:

| Scenario | Stage | What Happens |
|---|---|---|
| `missing_dep` | BUILD | Missing boto3 - agent proposes adding to requirements.txt |
| `failing_test` | TEST | AssertionError - escalates (could be real regression) |
| `bad_config` | DEPLOY | Missing DATABASE_URL - escalates (secret needed) |
| `slow_deploy` | DEPLOY | Health check timeout - escalates |
| `risky_iam_change` | DEPLOY (pass) | Wildcard IAM detected - always escalates |
| `clean_pass` | - | No issues, logs and moves on |

---

## Project Structure

```
agent/                     Core AI agent
  pipeline_doctor.py       Main orchestration loop (diagnose -> fix -> verify)
  log_analyzer.py          Parse & categorize CI/CD failures via regex
  policy_engine.py         Auto-fix vs. escalate decision logic
  rag_retriever.py         Bedrock Knowledge Base queries (RAG)
  fix_applicator.py        Commit fixes via GitHub API (PRs)
  notifier.py              Slack notifications (Block Kit)
  models.py                Shared data models & enums

backend/                   FastAPI REST API
  app.py                   Dashboard backend + approval workflow + S3 sync

frontend/                  React (Vite) dashboard
  src/App.jsx              Main app with tabs
  src/components/
    DemoPanel.jsx          One-click scenario triggers
    ObservabilityTab.jsx   Agent action trace (full transparency)
    ApprovalsTab.jsx       Human-in-the-loop approval/deny
    ResultsTab.jsx         Historical results table
    StatsBar.jsx           Live stats counters

infra/                     AWS CDK infrastructure
  pipeline_doctor_stack.py S3 + Lambda + API Gateway + IAM

knowledge_base/            RAG documents
  runbooks/                One runbook per failure scenario
  policies/                Auto-fix policy definitions

lambda/                    AWS Lambda handler
  lambda_handler.py        S3 event + API Gateway -> agent
```

---

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Required for AI diagnosis
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5

# Required for auto-fix (opening PRs)
GITHUB_TOKEN=<your-github-pat-with-repo-scope>
GITHUB_REPO_OWNER=sanyapeter
GITHUB_REPO_NAME=Dummy_Pipeline

# Optional - RAG Knowledge Base
BEDROCK_KB_ID=<your-kb-id>

# Optional - Slack notifications
SLACK_WEBHOOK_URL=<your-slack-webhook>
SLACK_CHANNEL=#pipeline-alerts

# Policy thresholds
AUTO_FIX_MAX_STEPS=4
ESCALATE_STEPS_THRESHOLD=5
REQUIRE_APPROVAL_FOR_PRODUCTION=true
```

Note: No secrets are committed to this repository. All credentials are loaded from environment variables or AWS Secrets Manager at runtime.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/pipeline-event` | Submit a pipeline event for AI processing |
| POST | `/api/events` | Lambda posts processed event + result |
| GET | `/api/events` | List all processed events (dashboard) |
| GET | `/api/events/{id}` | Get event detail + action trace |
| GET | `/api/approvals` | List pending human approvals |
| POST | `/api/approvals/{fix_id}/approve` | Approve a fix (triggers apply) |
| POST | `/api/approvals/{fix_id}/deny` | Deny a fix |
| GET | `/api/stats` | Dashboard summary statistics |
| GET | `/health` | Health check |

---

## Security & Threat Model

### Identity & Access
- Lambda IAM role uses least-privilege: only S3 read/write, Bedrock InvokeModel, and Bedrock Retrieve
- No wildcard resource permissions except Bedrock model access (required by AWS)
- GitHub token scoped to repo-level access only

### Secrets Management
- No secrets committed to source code (verified by .gitignore for `.env`)
- `.env.example` contains placeholder values only
- Production: GitHub token retrieved from AWS Secrets Manager at Lambda cold start
- All sensitive config loaded via environment variables

### Prompt/Input Security
- Pipeline error messages are truncated (500 char max) before sending to Bedrock to limit injection surface
- System prompts are hardcoded (not user-controllable)
- Claude responses are validated as JSON; malformed responses trigger safe fallback behavior
- Agent cannot execute arbitrary code - it only proposes file changes via GitHub PR

### Agent/Tool Security
- The agent can ONLY: read S3 logs, call Bedrock, create GitHub branches/PRs, and post to Slack
- It cannot delete repos, merge PRs, or deploy to production directly
- High-risk actions (infra changes, production deployments) always require human approval
- Policy Engine acts as a hard gate before any auto-fix is applied
- Maximum 4 steps for auto-fix; anything requiring more is escalated

### Abuse & Cost Controls
- Lambda timeout: 300 seconds (hard cap on execution time)
- Bedrock max_tokens: 2048 per call (prevents runaway token usage)
- Auto-fix limited to 4 steps max
- Only 2 Bedrock API calls per event (diagnosis + fix generation)
- S3 results stored for audit trail

### Supply Chain
- Python dependencies: boto3, fastapi, structlog, pydantic, PyGithub, httpx, python-dotenv
- Frontend: React, Vite, Tailwind CSS
- All from official PyPI/npm registries
- No custom Docker images in the critical path

---

## AI Governance & Responsible AI

### Purpose & Scope
- **Intended use:** Automated diagnosis and fix of CI/CD pipeline failures
- **Users:** DevOps engineers, platform teams, developers
- **Non-goals:** Not intended for production application code review, security vulnerability patching, or replacing human judgment on architectural decisions
- **Prohibited uses:** Must not be used to auto-merge PRs without human review on production branches

### Risk Classification
- **Low risk:** Missing dependency fixes, lint error fixes (auto-applied)
- **Medium risk:** Test failures, build errors (may auto-apply with low step count)
- **High risk:** Infrastructure changes, production branch modifications, permission errors (always escalated)
- **Critical:** Any change touching IAM, secrets, or security configurations (always escalated)

### Human Oversight
- All HIGH/CRITICAL risk fixes require explicit human approval before application
- Dashboard provides full action trace showing every agent decision
- Slack notifications include approve/deny buttons with context
- Humans can deny any fix at any point, even after approval (by closing the PR)
- Production branch changes always require human approval regardless of complexity

### Transparency
- Every step the agent takes is logged in the action trace (visible in Observability tab)
- Confidence scores are displayed for each diagnosis
- RAG sources are recorded showing which runbooks informed the decision
- Fix PRs include full metadata: fix ID, risk level, steps taken, and "generated by Pipeline Doctor" disclaimer

### Model/Provider
- **Model:** Anthropic Claude Sonnet 4.6 via Amazon Bedrock Converse API
- **Region:** us-east-1
- **Temperature:** 0.2 (low creativity, high consistency)
- **Max tokens:** 2048 per call
- **RAG:** Amazon Bedrock Knowledge Base (vector search, up to 5 passages)

### Monitoring
- Structured logging via structlog (JSON format, queryable)
- Action traces stored per event for auditability
- S3 results for historical analysis
- Dashboard stats: total events, auto-fixed, awaiting approval, failed fixes

### Incident Response
- If the agent produces an incorrect fix: human denies on dashboard, no code is merged
- If auto-fix breaks the pipeline further: CI re-run on the fix branch catches it before merge
- If Bedrock is unavailable: graceful fallback with "diagnosis unavailable" status
- If RAG returns no results: agent still functions using Claude's built-in knowledge (degraded mode)

---

## Observability

### Logging
- All agent actions logged via structlog (structured JSON)
- Key events: `received_event`, `failure_parsed`, `rag_retrieved`, `diagnosis_complete`, `fix_proposed`, `policy_decision`, `fix_applied` or `approval_requested`
- Each log entry includes: timestamp, event_id, pipeline_id, relevant metadata

### Action Trace
Every event processed generates a full action trace visible in the dashboard Observability tab:
```json
[
  {"action": "received_event", "timestamp": "...", "event_id": "evt-001", "status": "FAILED"},
  {"action": "failure_parsed", "timestamp": "...", "category": "missing_dependency", "stage": "BUILD"},
  {"action": "rag_retrieved", "timestamp": "...", "count": 3},
  {"action": "diagnosis_complete", "timestamp": "...", "root_cause": "...", "confidence": 0.92},
  {"action": "fix_proposed", "timestamp": "...", "fix_id": "fix-a1b2c3d4", "risk": "low"},
  {"action": "fix_applied", "timestamp": "...", "pr_url": "https://github.com/..."}
]
```

### Metrics (Dashboard)
- Total events processed
- Auto-fixed count
- Awaiting approval count
- Fix failed count
- Pending approvals

---

## Reliability & Failure Handling

| Failure Mode | Behavior |
|---|---|
| Bedrock unavailable | Returns "diagnosis unavailable" status; no fix attempted |
| RAG Knowledge Base not configured | Agent proceeds without RAG (uses Claude's training data only) |
| GitHub token missing | Fix application skipped; diagnosis still returned |
| Slack not configured | Notifications skipped silently; approval still appears on dashboard |
| JSON parse failure from Claude | Falls back to raw text as root cause with 0.5 confidence |
| Lambda timeout (300s) | Event marked as failed; can be retried |
| S3 read failure | Backend returns cached in-memory results |

### Rollback Strategy
- Fixes are applied via Pull Requests (never direct commits to main)
- Any fix PR can be closed/reverted by a human at any time
- CI re-runs on the fix branch before merge validates the fix works
- If a fix PR breaks tests, it will not be merged (standard branch protection)

---

## CI/CD & Deployment

### Infrastructure as Code (AWS CDK)
```bash
cd infra
pip install -r requirements.txt
cdk bootstrap
cdk deploy
```

The CDK stack (`infra/pipeline_doctor_stack.py`) provisions:
- Lambda function (`pipeline-doctor-trigger`) with Python 3.12 runtime
- IAM role with least-privilege policies (S3, Bedrock)
- API Gateway HTTP API with POST `/pipeline-event`
- References existing S3 bucket for log storage
- CORS configured for frontend access

### Deployment Pipeline
1. Code pushed to GitHub
2. CDK synthesizes CloudFormation template
3. `cdk deploy` provisions/updates infrastructure
4. Lambda code packaged from `deploy_package/` directory
5. API Gateway endpoint available immediately

---

## Testing

### Running Tests Locally
```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

### Test Coverage
- **Unit tests:** LogAnalyzer pattern matching, PolicyEngine decision logic, model validation
- **Integration tests:** Backend API endpoints, event processing flow
- **Failure-path tests:** Bedrock unavailable, malformed events, missing credentials
- **Security tests:** Prompt injection attempts, oversized payloads, invalid JSON

### Testing Without AWS
Post a pre-processed result to test the frontend + backend flow:
```bash
curl -X POST http://localhost:8000/api/events \
  -H "Content-Type: application/json" \
  -d '{
    "event": {"event_id": "test-1", "pipeline_id": "99", "status": "FAILED", "stage": "BUILD", "error": "test error", "source": "test"},
    "result": {"event_id": "test-1", "status": "auto_fixed", "message": "Fixed it", "fix_status": "applied", "fix": null, "actions": [{"action": "received_event", "timestamp": "2026-01-01T00:00:00"}]}
  }'
```

---

## AI Tool Usage Disclosure

This project was built using the following AI-assisted tools:

| Tool | Purpose |
|---|---|
| Amazon Bedrock (Claude Sonnet) | Core AI - pipeline diagnosis and fix generation (production use) |
| Kiro IDE (AI coding assistant) | Development assistance - code generation, debugging, documentation |
| GitHub Copilot | Code completion during development |

All AI-generated code was reviewed, tested, and validated by team members before inclusion.

---

## Technology & Dependency Inventory

### Backend
| Package | Version | License | Purpose |
|---|---|---|---|
| boto3 | latest | Apache 2.0 | AWS SDK (Bedrock, S3) |
| fastapi | latest | MIT | REST API framework |
| uvicorn | latest | BSD | ASGI server |
| structlog | latest | Apache 2.0/MIT | Structured logging |
| pydantic | latest | MIT | Data validation |
| PyGithub | latest | LGPL 3.0 | GitHub API for PRs |
| httpx | latest | BSD | HTTP client (Slack) |
| python-dotenv | latest | BSD | Env var loading |

### Frontend
| Package | Version | License | Purpose |
|---|---|---|---|
| react | 18+ | MIT | UI framework |
| vite | 5+ | MIT | Build tool |
| tailwindcss | 3+ | MIT | Styling |

### AWS Services
| Service | Purpose |
|---|---|
| Amazon Bedrock | Claude Sonnet 4.6 model invocation |
| Bedrock Knowledge Base | Vector search over runbooks |
| S3 | Log and result storage |
| Lambda | Serverless agent execution |
| API Gateway | HTTP API endpoint |
| IAM | Access control |
| CloudFormation (via CDK) | Infrastructure deployment |

---

## Demo Notes

### What is live/real:
- Bedrock Claude diagnosis and fix generation (real AI calls)
- Policy Engine decision logic (fully functional)
- Dashboard with real-time event display
- Approval workflow (approve/deny with state tracking)
- Observability trace (every agent step recorded)
- S3 result persistence and retrieval

### What is mocked/stubbed for demo:
- GitHub PR creation (requires GITHUB_TOKEN with write access to test repo)
- Slack notifications (requires SLACK_WEBHOOK_URL)
- S3 event trigger (demo uses direct API POST instead of actual S3 notification)
- The Dummy Pipeline itself (pre-built failure scenarios rather than live GitHub Actions runs)

---

## Known Limitations & Future Roadmap

### Current Limitations
- In-memory event store (not persisted across backend restarts without S3)
- Single-region deployment (us-east-1 only)
- No authentication on the dashboard API (suitable for internal use only)
- RAG quality depends on runbook content in the Knowledge Base
- GitHub rate limits may affect high-volume auto-fix scenarios

### Future Roadmap
- [ ] DynamoDB for persistent event/approval storage
- [ ] Multi-region Bedrock deployment for resilience
- [ ] API authentication (Cognito or API keys)
- [ ] AgentCore deployment for production hosting
- [ ] Bedrock Guardrails integration for additional AI safety
- [ ] Support for GitLab and Bitbucket (not just GitHub)
- [ ] Feedback loop: learn from approved/denied fixes to improve future recommendations
- [ ] Cost tracking dashboard (Bedrock token usage per event)
- [ ] Webhook-based Slack interactivity (approve directly from Slack)

---

## Scalability

### Current Design
- Lambda scales automatically (concurrent executions per event)
- S3 handles unlimited log storage
- Stateless backend can be horizontally scaled behind a load balancer

### What Breaks at 10x
- In-memory store becomes a bottleneck (solution: DynamoDB)
- Bedrock API throttling at high concurrency (solution: request queuing + retries)
- GitHub API rate limits (solution: batching + token rotation)

### Scaling Strategy
- Replace in-memory store with DynamoDB (already designed for it)
- Add SQS queue between S3 trigger and Lambda for burst absorption
- Implement exponential backoff on Bedrock calls
- Cache RAG results for identical error patterns

---

## Runbook / Operations

### Starting the System
```bash
# Backend
source .venv/bin/activate && python3 -m uvicorn backend.app:app --port 8000

# Frontend
cd frontend && npm run dev

# Verify
curl http://localhost:8000/health
```

### Common Issues

| Symptom | Cause | Fix |
|---|---|---|
| `NoCredentialsError` | AWS not configured | Run `aws configure` |
| `AccessDeniedException` on Bedrock | Model not enabled | Enable Claude in AWS Console > Bedrock > Model access |
| Port 8000 in use | Previous process | `lsof -ti:8000 \| xargs kill` |
| Frontend blank page | Backend not running | Start backend first, check port 8000 |
| `ModuleNotFoundError` | Venv not activated | Run `source .venv/bin/activate` |

### Monitoring in Production
- CloudWatch Logs: Lambda execution logs
- S3 `results/` prefix: All processed events with full action traces
- Dashboard `/api/stats`: Real-time success/failure metrics
- Slack channel: Approval requests and fix results

---

## Repository Hygiene

- `.gitignore` excludes: `.env`, `.venv/`, `__pycache__/`, `node_modules/`, `.aws/`
- No secrets in commit history (verified)
- `.env.example` provides sanitized configuration template
- Structured commits with descriptive messages
- Branch protection recommended for `main`

---

## License

See [LICENSE](./LICENSE) file.
