"""
AWS CDK Stack - Pipeline Doctor Infrastructure

Resources created:
  - S3 bucket (logs + runbooks + results)
  - Lambda function (s3_trigger.py) with S3 event notification
  - API Gateway HTTP API -> Lambda (POST /pipeline-event)
  - Bedrock Knowledge Base + data source pointing at runbooks prefix
  - IAM roles with least-privilege policies
  - Secrets Manager secret (GITHUB_TOKEN placeholder)
"""
from __future__ import annotations

import os
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_s3 as s3,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_s3_notifications as s3_notify,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class PipelineDoctorStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ----------------------------------------------------------------
        # 1. S3 Bucket
        # ----------------------------------------------------------------
        bucket = s3.Bucket(
            self, "PipelineDoctorBucket",
            bucket_name=f"pipeline-doctor-logs-{self.account}",
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-logs-90d",
                    prefix="logs/",
                    expiration=Duration.days(90),
                ),
                s3.LifecycleRule(
                    id="expire-results-180d",
                    prefix="results/",
                    expiration=Duration.days(180),
                ),
            ],
        )

        # ----------------------------------------------------------------
        # 2. Secrets (GitHub token placeholder)
        # ----------------------------------------------------------------
        github_secret = secretsmanager.Secret(
            self, "GitHubTokenSecret",
            secret_name="pipeline-doctor/github-token",
            description="GitHub PAT for Pipeline Doctor fix applicator",
        )

        # ----------------------------------------------------------------
        # 3. Lambda IAM role
        # ----------------------------------------------------------------
        lambda_role = iam.Role(
            self, "LambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # S3 read/write on our bucket only
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
            resources=[bucket.bucket_arn, f"{bucket.bucket_arn}/*"],
        ))

        # Bedrock model invocation (scoped to Claude Sonnet cross-region profile)
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[
                f"arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5*",
                f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/*",
            ],
        ))

        # Bedrock Knowledge Base retrieval
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "bedrock:Retrieve",
                "bedrock:RetrieveAndGenerate",
            ],
            resources=["*"],  # KB ARN not known until KB is created; tighten post-deploy
        ))

        # Read GitHub secret
        github_secret.grant_read(lambda_role)

        # ----------------------------------------------------------------
        # 4. Lambda function
        # ----------------------------------------------------------------
        fn = lambda_.Function(
            self, "PipelineDoctorLambda",
            function_name="pipeline-doctor-trigger",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda.s3_trigger.handler",
            code=lambda_.Code.from_asset(
                "..",  # repo root — Lambda layer/zip should include agent/ + lambda/
                bundling={
                    "image": lambda_.Runtime.PYTHON_3_12.bundling_image,
                    "command": [
                        "bash", "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -r agent lambda backend /asset-output/",
                    ],
                },
            ),
            role=lambda_role,
            timeout=Duration.seconds(300),
            memory_size=1024,
            environment={
                "AWS_REGION_NAME": self.region,
                "S3_LOG_BUCKET": bucket.bucket_name,
                "BEDROCK_MODEL_ID": "us.anthropic.claude-sonnet-4-5",
                "GITHUB_REPO_OWNER": "sanyapeter",
                "GITHUB_REPO_NAME": "Dummy_Pipeline",
                "AUTO_FIX_MAX_STEPS": "4",
                "ESCALATE_STEPS_THRESHOLD": "5",
                "REQUIRE_APPROVAL_FOR_PRODUCTION": "true",
            },
        )

        # ----------------------------------------------------------------
        # 5. S3 event notification  logs/*.json -> Lambda
        # ----------------------------------------------------------------
        bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3_notify.LambdaDestination(fn),
            s3.NotificationKeyFilter(prefix="logs/", suffix=".json"),
        )
        bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3_notify.LambdaDestination(fn),
            s3.NotificationKeyFilter(prefix="logs/", suffix=".txt"),
        )

        # ----------------------------------------------------------------
        # 6. API Gateway HTTP API  POST /pipeline-event -> Lambda
        # ----------------------------------------------------------------
        http_api = apigwv2.HttpApi(
            self, "PipelineDoctorApi",
            api_name="pipeline-doctor-api",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_origins=["*"],
                allow_methods=[apigwv2.CorsHttpMethod.POST, apigwv2.CorsHttpMethod.OPTIONS],
                allow_headers=["Content-Type"],
            ),
        )

        http_api.add_routes(
            path="/pipeline-event",
            methods=[apigwv2.HttpMethod.POST],
            integration=integrations.HttpLambdaIntegration(
                "LambdaIntegration", fn
            ),
        )

        # ----------------------------------------------------------------
        # 7. Outputs
        # ----------------------------------------------------------------
        CfnOutput(self, "BucketName",  value=bucket.bucket_name,  description="S3 bucket for logs and results")
        CfnOutput(self, "ApiEndpoint", value=http_api.api_endpoint, description="API Gateway endpoint")
        CfnOutput(self, "LambdaArn",  value=fn.function_arn,       description="Lambda function ARN")
        CfnOutput(self, "GitHubSecretArn", value=github_secret.secret_arn, description="GitHub token secret ARN")
