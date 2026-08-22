#!/bin/bash
# Build the Lambda deployment package
set -e

echo "Building Lambda deployment package..."

rm -rf deploy_package
mkdir deploy_package

# Install dependencies into the package
pip install boto3 structlog httpx PyGithub pydantic -t deploy_package -q

# Copy our code
cp -r agent deploy_package/
mkdir -p deploy_package/lambda
cp lambda/s3_trigger.py deploy_package/lambda/
cp lambda/__init__.py deploy_package/lambda/

# Create the top-level handler that Lambda expects
cat > deploy_package/lambda_handler.py << 'EOF'
"""Top-level Lambda handler that delegates to s3_trigger."""
from lambda.s3_trigger import handler
EOF

echo "Done! Deploy package at: deploy_package/"
echo "Size: $(du -sh deploy_package | cut -f1)"
