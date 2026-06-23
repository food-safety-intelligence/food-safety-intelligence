#!/bin/bash
#
# ALB Setup Script — Food Safety Intelligence
#
# Creates Application Load Balancer and binds to Lambda proxy function.
#
# Prerequisites:
#   - Lambda function already created (run deploy_aws.sh first)
#   - VPC with public subnets
#
# Usage:
#   ./scripts/alb_setup.sh [region] [account-id] [vpc-id]
#

set -e

REGION="${1:-us-west-2}"
ACCOUNT="${2:-991500268971}"
VPC_ID="${3:-}"

LAMBDA_FUNC_NAME="food-safety-agent-proxy"
ALB_NAME="food-safety-alb"
ALB_SG_NAME="food-safety-alb-sg"
TG_NAME="food-safety-lambda-targets"

echo "=========================================="
echo "ALB Setup — Food Safety Intelligence"
echo "=========================================="
echo "Region:   $REGION"
echo "Account:  $ACCOUNT"
echo "VPC ID:   ${VPC_ID:-(auto-detect)}"
echo ""

# ── Step 1: Get Lambda ARN ──────────────────────────────────────────────────
echo "[1/6] Retrieving Lambda function..."
LAMBDA_ARN=$(aws lambda get-function \
    --function-name "$LAMBDA_FUNC_NAME" \
    --query 'Configuration.FunctionArn' \
    --output text \
    --region "$REGION" 2>/dev/null || echo "")

if [ -z "$LAMBDA_ARN" ]; then
    echo "❌ ERROR: Lambda function '$LAMBDA_FUNC_NAME' not found."
    echo "   Run deploy_aws.sh first."
    exit 1
fi
echo "✓ Lambda ARN: $LAMBDA_ARN"
echo ""

# ── Step 2: Get VPC ID ──────────────────────────────────────────────────────
if [ -z "$VPC_ID" ]; then
    echo "[2/6] Auto-detecting VPC..."
    VPC_ID=$(aws ec2 describe-vpcs \
        --filters "Name=isDefault,Values=true" \
        --query 'Vpcs[0].VpcId' \
        --output text \
        --region "$REGION")
fi

if [ -z "$VPC_ID" ] || [ "$VPC_ID" = "None" ]; then
    echo "❌ ERROR: Could not determine VPC ID."
    echo "   Specify manually: ./alb_setup.sh $REGION $ACCOUNT vpc-xxxxx"
    exit 1
fi
echo "✓ VPC ID: $VPC_ID"
echo ""

# ── Step 3: Ensure ALB security group ───────────────────────────────────────
echo "[3/6] Provisioning ALB security group..."
ALB_SG_ID=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=$ALB_SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
    --query 'SecurityGroups[0].GroupId' \
    --output text \
    --region "$REGION" 2>/dev/null || true)

if [ -z "$ALB_SG_ID" ] || [ "$ALB_SG_ID" = "None" ]; then
    ALB_SG_ID=$(aws ec2 create-security-group \
        --group-name "$ALB_SG_NAME" \
        --description "Security group for public ALB" \
        --vpc-id "$VPC_ID" \
        --region "$REGION" \
        --query 'GroupId' \
        --output text)
    aws ec2 authorize-security-group-ingress \
        --group-id "$ALB_SG_ID" \
        --protocol tcp \
        --port 80 \
        --cidr 0.0.0.0/0 \
        --region "$REGION" \
        --output text > /dev/null
    aws ec2 authorize-security-group-ingress \
        --group-id "$ALB_SG_ID" \
        --protocol tcp \
        --port 443 \
        --cidr 0.0.0.0/0 \
        --region "$REGION" \
        --output text > /dev/null
    aws ec2 authorize-security-group-egress \
        --group-id "$ALB_SG_ID" \
        --protocol -1 \
        --cidr 0.0.0.0/0 \
        --region "$REGION" \
        --output text > /dev/null
    echo "✓ Security group created: $ALB_SG_ID"
else
    echo "✓ Security group already exists: $ALB_SG_ID"
fi

echo ""

# ── Step 4: Create Target Group ─────────────────────────────────────────────
echo "[4/6] Creating target group..."
TG_ARN=$(aws elbv2 describe-target-groups \
    --names "$TG_NAME" \
    --region "$REGION" \
    --query 'TargetGroups[0].TargetGroupArn' \
    --output text 2>/dev/null || true)

if [ -z "$TG_ARN" ] || [ "$TG_ARN" = "None" ]; then
    TG_ARN=$(aws elbv2 create-target-group \
        --name "$TG_NAME" \
        --target-type lambda \
        --region "$REGION" \
        --query 'TargetGroups[0].TargetGroupArn' \
        --output text)
    echo "✓ Target group created: $TG_ARN"
else
    echo "✓ Target group already exists: $TG_ARN"
fi
echo ""

# ── Step 4: Register Lambda with Target Group ────────────────────────────────
echo "[4/6] Registering Lambda with target group..."
aws elbv2 register-targets \
    --target-group-arn "$TG_ARN" \
    --targets Id="$LAMBDA_ARN" \
    --region "$REGION" \
    --output text > /dev/null 2>&1 || true

# Grant permission
aws lambda add-permission \
    --function-name "$LAMBDA_FUNC_NAME" \
    --statement-id AllowALB \
    --action lambda:InvokeFunction \
    --principal elasticloadbalancing.amazonaws.com \
    --source-arn "$TG_ARN" \
    --region "$REGION" \
    --output text > /dev/null 2>&1 || true

echo "✓ Lambda registered with target group"
echo ""

# ── Step 5: Get Subnets ─────────────────────────────────────────────────────
echo "[5/6] Getting public subnets..."
SUBNETS=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=$VPC_ID" \
    --query 'Subnets[0:2].SubnetId' \
    --output text \
    --region "$REGION")

SUBNET_COUNT=$(echo $SUBNETS | wc -w)
if [ "$SUBNET_COUNT" -lt 2 ]; then
    echo "⚠ Warning: Only $SUBNET_COUNT subnet(s) found. ALB requires at least 2."
fi

echo "✓ Subnets: $SUBNETS"
echo ""

# ── Step 6: Create ALB ──────────────────────────────────────────────────────
echo "[6/6] Creating Application Load Balancer..."

ALB_ARN=$(aws elbv2 describe-load-balancers \
    --names "$ALB_NAME" \
    --region "$REGION" \
    --query 'LoadBalancers[0].LoadBalancerArn' \
    --output text 2>/dev/null || true)

if [ -z "$ALB_ARN" ] || [ "$ALB_ARN" = "None" ]; then
    ALB_ARN=$(aws elbv2 create-load-balancer \
        --name "$ALB_NAME" \
        --subnets $SUBNETS \
        --security-groups "$ALB_SG_ID" \
        --scheme internet-facing \
        --type application \
        --region "$REGION" \
        --query 'LoadBalancers[0].LoadBalancerArn' \
        --output text)
    
    ALB_DNS=$(aws elbv2 describe-load-balancers \
        --load-balancer-arns "$ALB_ARN" \
        --region "$REGION" \
        --query 'LoadBalancers[0].DNSName' \
        --output text)
    
    echo "✓ ALB created: $ALB_ARN"
    echo "✓ ALB DNS: $ALB_DNS"
    
    # Create listener
    echo ""
    echo "Creating HTTP listener..."
    aws elbv2 create-listener \
        --load-balancer-arn "$ALB_ARN" \
        --protocol HTTP \
        --port 80 \
        --default-actions Type=forward,TargetGroupArn="$TG_ARN" \
        --region "$REGION" \
        --output text > /dev/null
    
    echo "✓ Listener created"
else
    aws elbv2 set-security-groups \
        --load-balancer-arn "$ALB_ARN" \
        --security-groups "$ALB_SG_ID" \
        --region "$REGION" \
        --output text > /dev/null
    ALB_DNS=$(aws elbv2 describe-load-balancers \
        --load-balancer-arns "$ALB_ARN" \
        --region "$REGION" \
        --query 'LoadBalancers[0].DNSName' \
        --output text)
    
    echo "✓ ALB already exists: $ALB_ARN"
    echo "✓ ALB DNS: $ALB_DNS"
fi

echo ""
echo "=========================================="
echo "ALB Setup Complete"
echo "=========================================="
echo ""
echo "Endpoint: http://$ALB_DNS/"
echo ""
echo "Test with:"
echo ""
echo "  curl -X POST http://$ALB_DNS/ \\"
echo "    -H \"Content-Type: application/json\" \\"
echo '    -d '"'"'{"query": "safe sushi near Wicker Park", "session_id": "test-123"}'"'"
echo ""
echo "Integration:"
echo "  1. Update app/.env.local:"
echo "     NEXT_PUBLIC_API_URL=http://$ALB_DNS"
echo "  2. Start web app: cd app && pnpm dev"
echo ""
echo "✅ Ready for integration!"
