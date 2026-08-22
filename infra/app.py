#!/usr/bin/env python3
import aws_cdk as cdk
from pipeline_doctor_stack import PipelineDoctorStack

app = cdk.App()
PipelineDoctorStack(
    app, "PipelineDoctorStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account") or None,
        region=app.node.try_get_context("region") or "us-east-1",
    ),
    description="Pipeline Doctor - AI-powered CI/CD failure diagnosis and auto-fix",
)
app.synth()
