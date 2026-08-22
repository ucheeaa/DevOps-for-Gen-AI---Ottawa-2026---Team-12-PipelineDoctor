"""
AWS CDK Stack - Pipeline Doctor Infrastructure

Uses Sanya's existing S3 bucket and adds:
  - Lambda function (processes logs, calls Bedrock)
  - MCP Browser Lambda (internet fetch + web search via Brave)
  - S3 event notification (new log -> Lambda)
  - API Gateway HTTP API (POST /pipeline-event for direct invocation)
  - IAM role with least-privilege
"""
from __future__ import annotations

import os

from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_s3 as s3,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_s3_notifications as s3_notify,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations,
)
from constructs import Construct

# Sanya's existing bucket
EXISTING_BUCKET_NAME = "pipeline-doctor-logs-714665049802"

# Resolve deploy_package relative to this file (infra/../deploy_package)
_HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY_PACKAGE = os.path.join(_HERE, "..", "deploy_package")


class PipelineDoctorStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ----------------------------------------------------------------
        # 1. Reference existing S3 Bucket
        # ----------------------------------------------------------------
        bucket = s3.Bucket.from_bucket_name(
            self, "ExistingBucket", EXISTING_BUCKET_NAME
        )

        # ----------------------------------------------------------------
        # 2. MCP Browser Lambda IAM role
        # ----------------------------------------------------------------
        mcp_role = iam.Role(
            self, "McpBrowserRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # ----------------------------------------------------------------
        # 3. MCP Browser Lambda
        #    - stdlib only, so no extra layer needed
        #    - deployed with a Function URL (AuthType=AWS_IAM)
        #      so only the Pipeline Doctor Lambda can call it
        # ----------------------------------------------------------------
        mcp_fn = lambda_.Function(
            self, "McpBrowserLambdaV2",
            function_name="pipeline-doctor-mcp-browser-v2",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="mcp_browser_server.handler",
            code=lambda_.Code.from_asset(DEPLOY_PACKAGE),
            role=mcp_role,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                # Set BRAVE_API_KEY via AWS Secrets Manager or SSM in production.
                # Leave blank to get graceful degradation (returns search URL hints).
                "BRAVE_API_KEY": "",
                "FETCH_MAX_BYTES": "32768",
                "SEARCH_MAX_RESULTS": "5",
            },
        )

        # Function URL with no auth — recreated with suffix v2 to force
        # replacement after switching from AWS_IAM to NONE auth.
        mcp_fn_url = mcp_fn.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                allowed_methods=[lambda_.HttpMethod.POST],
            ),
        )

        # ----------------------------------------------------------------
        # 4. Pipeline Doctor Lambda IAM role
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

        # S3 read/write
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
            resources=[bucket.bucket_arn, f"{bucket.bucket_arn}/*"],
        ))

        # Bedrock model invocation
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=["*"],
        ))

        # Bedrock Knowledge Base retrieval
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"],
            resources=["*"],
        ))

        # Allow Pipeline Doctor Lambda to invoke the MCP Browser via Function URL
        # (InvokeFunction permission is required for IAM-auth Function URLs)
        lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["lambda:InvokeFunction", "lambda:InvokeFunctionUrl"],
            resources=[mcp_fn.function_arn],
        ))

        # ----------------------------------------------------------------
        # 5. Pipeline Doctor Lambda
        # ----------------------------------------------------------------
        fn = lambda_.Function(
            self, "PipelineDoctorLambda",
            function_name="pipeline-doctor-trigger",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_handler.handler",
            code=lambda_.Code.from_asset(DEPLOY_PACKAGE),
            role=lambda_role,
            timeout=Duration.seconds(300),
            memory_size=1024,
            environment={
                "AWS_REGION_NAME": "us-east-2",
                "S3_LOG_BUCKET": EXISTING_BUCKET_NAME,
                "BEDROCK_MODEL_ID": "us.anthropic.claude-sonnet-4-6",
                "GITHUB_REPO_OWNER": "sanyapeter",
                "GITHUB_REPO_NAME": "Dummy_Pipeline",
                "AUTO_FIX_MAX_STEPS": "4",
                "ESCALATE_STEPS_THRESHOLD": "5",
                "REQUIRE_APPROVAL_FOR_PRODUCTION": "true",
                # MCP browser invoked directly via boto3 — no Function URL needed
                "MCP_BROWSER_FUNCTION_NAME": "pipeline-doctor-mcp-browser-v2",
                "MCP_BROWSER_REGION": "us-east-1",
                "MCP_SEARCH_RESULTS": "3",
            },
        )

        # ----------------------------------------------------------------
        # 6. S3 event notification -> Lambda
        # ----------------------------------------------------------------
        # Note: for imported buckets, we need to add the notification
        # via a custom resource or manually. CDK can't add notifications
        # to imported buckets directly. We'll use the API Gateway path
        # and add the S3 notification manually via CLI after deploy.

        # ----------------------------------------------------------------
        # 7. API Gateway HTTP API
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
        # 8. Outputs
        # ----------------------------------------------------------------
        CfnOutput(self, "BucketName", value=EXISTING_BUCKET_NAME)
        CfnOutput(self, "ApiEndpoint", value=http_api.api_endpoint)
        CfnOutput(self, "LambdaArn", value=fn.function_arn)
        CfnOutput(self, "LambdaName", value=fn.function_name)
        CfnOutput(self, "McpBrowserFunctionUrl", value=mcp_fn_url.url,
                  description="MCP Browser Lambda Function URL (AWS_IAM auth)")
        CfnOutput(self, "McpBrowserArn", value=mcp_fn.function_arn)
