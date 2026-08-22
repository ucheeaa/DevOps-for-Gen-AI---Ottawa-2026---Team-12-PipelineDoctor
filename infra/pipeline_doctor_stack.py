"""
AWS CDK Stack - Pipeline Doctor Infrastructure

Uses Sanya's existing S3 bucket and adds:
  - Lambda function (processes logs, calls Bedrock)
  - S3 event notification (new log -> Lambda)
  - API Gateway HTTP API (POST /pipeline-event for direct invocation)
  - IAM role with least-privilege
"""
from __future__ import annotations

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
        # 2. Lambda IAM role
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

        # ----------------------------------------------------------------
        # 3. Lambda function
        # ----------------------------------------------------------------
        fn = lambda_.Function(
            self, "PipelineDoctorLambda",
            function_name="pipeline-doctor-trigger",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_handler.handler",
            code=lambda_.Code.from_asset("../deploy_package"),
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
            },
        )

        # ----------------------------------------------------------------
        # 4. S3 event notification -> Lambda
        # ----------------------------------------------------------------
        # Note: for imported buckets, we need to add the notification
        # via a custom resource or manually. CDK can't add notifications
        # to imported buckets directly. We'll use the API Gateway path
        # and add the S3 notification manually via CLI after deploy.

        # ----------------------------------------------------------------
        # 5. API Gateway HTTP API
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
        # 6. Outputs
        # ----------------------------------------------------------------
        CfnOutput(self, "BucketName", value=EXISTING_BUCKET_NAME)
        CfnOutput(self, "ApiEndpoint", value=http_api.api_endpoint)
        CfnOutput(self, "LambdaArn", value=fn.function_arn)
        CfnOutput(self, "LambdaName", value=fn.function_name)
