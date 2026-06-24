#!/bin/bash
#
# Food Safety Intelligence — AWS Deployment Script
# Automates CDK deployment + Lambda + ALB setup
#
# Usage:
#   ./scripts/deploy_aws.sh [region] [account-id]
#
# Defaults:
#   region: us-west-2
#   account-id: 991500268971
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

REGION="${1:-us-west-2}"
ACCOUNT="${2:-991500268971}"
PROJECT_NAME="foodsafety"
ENV="${3:-default}"

echo "=========================================="
echo "Food Safety Intelligence — AWS Deployment"
echo "=========================================="
echo "Region:  $REGION"
echo "Account: $ACCOUNT"
echo "Project: $PROJECT_NAME"
echo "Environment: $ENV"
echo ""

# ── Step 1: Verify AWS Credentials ──────────────────────────────────────────
echo "[1/7] Verifying AWS credentials..."
CALLER_ID=$(aws sts get-caller-identity --query 'Account' --output text 2>&1 || echo "FAILED")
if [ "$CALLER_ID" != "$ACCOUNT" ]; then
    echo "❌ ERROR: AWS credentials not configured or wrong account."
    echo "   Expected account: $ACCOUNT"
    echo "   Got account: $CALLER_ID"
    echo ""
    echo "   To fix, run:"
    echo "   $ aws login"
    echo "   or"
    echo "   $ aws configure"
    exit 1
fi
echo "✓ AWS credentials verified. Account: $ACCOUNT"
echo ""

# ── Step 2: Verify S3 Data Files ────────────────────────────────────────────
echo "[2/7] Verifying S3 data files..."
DATA_BUCKET="food-safety-intelligence-data"
for file in "scores.json" "inspection_history.json"; do
    if aws s3 ls "s3://$DATA_BUCKET/web-app-data/$file" --region "$REGION" &>/dev/null; then
        echo "✓ Found s3://$DATA_BUCKET/web-app-data/$file"
    else
        echo "⚠ Missing s3://$DATA_BUCKET/web-app-data/$file"
        echo "  Upload from $REPO_ROOT/data/processed/ before continuing."
    fi
done
echo ""

# ── Step 3: Build CDK ───────────────────────────────────────────────────────
echo "[3/7] Building CDK stack..."
cd "$REPO_ROOT/agentcore-deploy/agentcore/cdk"
npm run build 2>&1 | tail -5
echo "✓ CDK built successfully"
echo ""

# ── Step 4: Deploy CDK ──────────────────────────────────────────────────────
echo "[4/7] Deploying AgentCore Runtime (CDK)..."
STACK_NAME="AgentCore-$PROJECT_NAME-$ENV"
npm run cdk -- deploy \
    --all \
    --require-approval=never \
    --region "$REGION" \
    2>&1 | tail -10

# Extract Agent Runtime ARN
echo "Waiting for stack outputs..."
sleep 5
AGENT_RUNTIME_ARN=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`AgentCoreRuntimeArn`].OutputValue' \
    --output text \
    --region "$REGION" 2>/dev/null || echo "")

if [ -z "$AGENT_RUNTIME_ARN" ]; then
    echo "⚠ Warning: Could not retrieve Agent Runtime ARN from CloudFormation."
    echo "  Manually retrieve from AWS console or:"
    echo "  aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION"
else
    echo "✓ Agent Runtime ARN: $AGENT_RUNTIME_ARN"
fi
echo ""

# ── Step 5: Create Lambda Proxy ─────────────────────────────────────────────
echo "[5/7] Packaging Lambda function..."
cd "$REPO_ROOT/agents/lambda_proxy"

if [ -d "dist" ]; then rm -rf dist; fi
mkdir -p dist
cp handler.py dist/

cd dist
pip install bedrock-agentcore boto3 -t . --quiet
rm -f ../lambda_proxy.zip
zip -q -r ../lambda_proxy.zip ./* 2>/dev/null || true
cd ..

if [ ! -f "lambda_proxy.zip" ]; then
    echo "❌ ERROR: Failed to create Lambda package"
    exit 1
fi
echo "✓ Lambda package created: agents/lambda_proxy/lambda_proxy.zip"
echo ""

echo "[6/7] Creating Lambda function..."

# Check if role exists; if not, create a basic one
ROLE_NAME="food-safety-lambda-role"
ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" \
    --query 'Role.Arn' --output text 2>/dev/null || echo "")

if [ -z "$ROLE_ARN" ]; then
    echo "Creating IAM role $ROLE_NAME..."
    ROLE_ARN=$(aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document '{
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }
            ]
        }' \
        --query 'Role.Arn' \
        --output text)
    
    # Attach policies
    aws iam attach-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
    
    # Add Bedrock + S3 access
    aws iam put-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name "BedrockAgentCoreAndS3Access" \
        --policy-document '{
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "bedrock-agentcore:InvokeAgentRuntime",
                        "bedrock:InvokeAgentRuntime",
                        "bedrock:InvokeModel"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:ListBucket"
                    ],
                    "Resource": [
                        "arn:aws:s3:::food-safety-intelligence-data",
                        "arn:aws:s3:::food-safety-intelligence-data/*"
                    ]
                }
            ]
        }'
    
    sleep 2  # Wait for role to be available
    echo "✓ IAM role created: $ROLE_ARN"
fi

# Create or update Lambda function
LAMBDA_FUNC_NAME="food-safety-agent-proxy"
LAMBDA_EXISTS=$(aws lambda get-function --function-name "$LAMBDA_FUNC_NAME" \
    --region "$REGION" 2>/dev/null || echo "")

if [ -z "$LAMBDA_EXISTS" ]; then
    echo "Creating Lambda function..."
    aws lambda create-function \
        --function-name "$LAMBDA_FUNC_NAME" \
        --runtime python3.11 \
        --role "$ROLE_ARN" \
        --handler handler.handler \
        --zip-file "fileb://lambda_proxy.zip" \
        --timeout 60 \
        --memory-size 512 \
        --environment "Variables={AGENT_RUNTIME_ARN=$AGENT_RUNTIME_ARN,DATA_BUCKET=$DATA_BUCKET}" \
        --region "$REGION" \
        --output text > /dev/null
else
    echo "Updating existing Lambda function..."
    aws lambda update-function-code \
        --function-name "$LAMBDA_FUNC_NAME" \
        --zip-file "fileb://lambda_proxy.zip" \
        --region "$REGION" \
        --output text > /dev/null
    
    aws lambda update-function-configuration \
        --function-name "$LAMBDA_FUNC_NAME" \
        --handler handler.handler \
        --environment "Variables={AGENT_RUNTIME_ARN=$AGENT_RUNTIME_ARN,DATA_BUCKET=$DATA_BUCKET}" \
        --region "$REGION" \
        --output text > /dev/null
fi

LAMBDA_ARN=$(aws lambda get-function \
    --function-name "$LAMBDA_FUNC_NAME" \
    --query 'Configuration.FunctionArn' \
    --output text \
    --region "$REGION")

echo "✓ Lambda function: $LAMBDA_ARN"
echo ""

# ── Step 7: Create ALB (Optional) ────────────────────────────────────────────
echo "[7/7] Setting up Application Load Balancer (optional)..."
echo ""
echo "Note: ALB setup requires VPC, subnets, and security group."
echo "Run the manual ALB setup from DEPLOY_AWS_ALB.md for now."
echo ""
echo "Quick reference for next steps:"
echo "  1. Get VPC ID: aws ec2 describe-vpcs --region $REGION --query 'Vpcs[0].VpcId'"
echo "  2. Create target group for Lambda"
echo "  3. Create ALB and listener"
echo "  4. Test endpoint: http://alb-dns-name/ with JSON body"
echo ""

# ── Summary ─────────────────────────────────────────────────────────────────
echo "=========================================="
echo "Deployment Summary"
echo "=========================================="
echo ""
echo "✓ CloudFormation Stack:   $STACK_NAME"
echo "✓ Agent Runtime ARN:      $AGENT_RUNTIME_ARN"
echo "✓ Lambda Function:        $LAMBDA_FUNC_NAME"
echo "✓ Lambda ARN:             $LAMBDA_ARN"
echo "✓ Data Bucket:            s3://$DATA_BUCKET/"
echo ""
echo "Next steps:"
echo "  1. Follow DEPLOY_AWS_ALB.md Part 5–7 to set up the ALB"
echo "  2. Test the agent: curl -X POST http://ALB-DNS/ -d '{\"query\": \"...\"}'"
echo "  3. Update app/.env.local with the ALB endpoint"
echo "  4. Start web app: cd app && pnpm dev"
echo ""
echo "✅ Deployment complete!"
