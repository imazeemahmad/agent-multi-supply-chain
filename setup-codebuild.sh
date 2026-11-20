#!/bin/bash
set -e

echo "=========================================="
echo "Building Agent Container Images"
echo "=========================================="

# Get build bucket and project from CloudFormation outputs
STACK_NAME=$(aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query "StackSummaries[?contains(StackName,'LabStack') && ends_with(StackName,'-0')].StackName | [0]" --output text)

if [ -z "$STACK_NAME" ] || [ "$STACK_NAME" = "None" ]; then
  echo "✗ Could not find lab stack (expected LabStack-*-0)."
  echo "  Available stacks:"
  aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
    --query "StackSummaries[].StackName" --output table
  echo "  Ensure the CDK stack is deployed."
  exit 1
fi

echo "Stack: $STACK_NAME"

BUILD_BUCKET=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='CodeBuildBucketName'].OutputValue" --output text)

PROJECT_NAME=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='CodeBuildProjectName'].OutputValue" --output text)

echo "Build Bucket: $BUILD_BUCKET"
echo "CodeBuild Project: $PROJECT_NAME"

# Package source code
echo ""
echo "Packaging source code..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

python3 -c "
import zipfile, os
with zipfile.ZipFile('/tmp/deployment.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__', 'tests')]
        for f in files:
            if f.endswith(('.pyc', '.DS_Store')) or f == 'cdk_stack.py':
                continue
            filepath = os.path.join(root, f)
            zf.write(filepath)
print('Done')
"

echo "✓ Source packaged"

# Upload to S3
echo "Uploading to S3..."
aws s3 cp /tmp/deployment.zip "s3://${BUILD_BUCKET}/deployment.zip"
echo "✓ Uploaded to s3://${BUILD_BUCKET}/deployment.zip"

# Start build
echo ""
echo "Starting CodeBuild..."
BUILD_ID=$(aws codebuild start-build --project-name "$PROJECT_NAME" \
  --query 'build.id' --output text)

echo "Build started: $BUILD_ID"
echo ""
echo "Waiting for build to complete (this takes 3-5 minutes)..."

# Poll for completion
while true; do
  STATUS=$(aws codebuild batch-get-builds --ids "$BUILD_ID" \
    --query 'builds[0].buildStatus' --output text)

  if [ "$STATUS" = "SUCCEEDED" ]; then
    echo ""
    echo "✓ Build completed successfully"
    echo "Container images pushed to ECR."
    echo ""
    echo "Next step: python scripts/deploy_agents.py"
    exit 0
  elif [ "$STATUS" = "FAILED" ] || [ "$STATUS" = "FAULT" ] || [ "$STATUS" = "STOPPED" ]; then
    echo ""
    echo "✗ Build failed with status: $STATUS"
    echo "Check CodeBuild logs for details."
    exit 1
  fi

  echo "  Status: $STATUS ..."
  sleep 15
done
