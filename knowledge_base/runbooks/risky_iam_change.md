# Runbook: Risky Infrastructure Change Detected (IAM / Security Group)

## Symptom
Pipeline passed, but static analysis or change detection identified:
- IAM policy with `Action: "iam:*"` and `Resource: "*"` (wildcard)
- Security group rule open to `0.0.0.0/0` on a wide port range (0-65535)

## Risk Classification
**CRITICAL** — Wildcard IAM permissions violate the principle of least
privilege. Open security groups expose resources to the internet.
**Human review is always required, regardless of step count.**

## Why This Is Flagged Even on a Passing Build
A pipeline can pass all tests while still introducing a security
vulnerability. Pipeline Doctor flags "risky changes" that do not cause a
build failure but should be reviewed before being applied to production.

## Required Human Actions
1. Review `terraform/main.tf` (or the equivalent IaC file) for the
   specific offending resource.
2. For IAM: replace wildcard actions with the minimum required set.
   Example fix:
   ```hcl
   # Before (wildcard - dangerous)
   actions   = ["iam:*"]
   resources = ["*"]

   # After (least privilege)
   actions   = ["iam:GetRole", "iam:PassRole"]
   resources = ["arn:aws:iam::ACCOUNT_ID:role/my-specific-role"]
   ```
3. For security groups: restrict the CIDR to the specific IP range or
   use VPC-internal CIDR blocks.
   ```hcl
   # Before
   cidr_blocks = ["0.0.0.0/0"]
   from_port   = 0
   to_port     = 65535

   # After
   cidr_blocks = ["10.0.0.0/8"]
   from_port   = 443
   to_port     = 443
   ```
4. Re-plan with `terraform plan` and verify the changes are correct.
5. Apply with human approval in the Pipeline Doctor dashboard.

## Policy Reference
- AWS Well-Architected: Security Pillar — Least Privilege Access
- CIS AWS Foundations Benchmark — IAM checks 1.16, 1.22
- SOC 2 CC6.3 — Logical access controls
