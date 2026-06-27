#!/bin/bash
#
# Test Script — Food Safety Intelligence Agent Endpoint
#
# Tests the ALB endpoint and verifies the agent is working.
#
# Usage:
#   ./scripts/test_agent.sh [alb-dns-or-url] [query]
#
# Examples:
#   ./scripts/test_agent.sh food-safety-alb-123.us-west-2.elb.amazonaws.com "safe pizza near Loop"
#   ./scripts/test_agent.sh http://localhost:3000 "restaurants in Wicker Park"
#

set -e

ALB_URL="${1:-}"
QUERY="${2:-safe sushi near Wicker Park}"

if [ -z "$ALB_URL" ]; then
    echo "Usage: $0 <alb-dns-or-url> [query]"
    echo ""
    echo "Examples:"
    echo "  $0 food-safety-alb-123.us-west-2.elb.amazonaws.com"
    echo "  $0 http://localhost:3000 'safe pizza near Loop'"
    exit 1
fi

# Add protocol if missing
if [[ ! "$ALB_URL" =~ ^https?:// ]]; then
    ALB_URL="http://$ALB_URL"
fi

# Ensure trailing slash
ALB_URL="${ALB_URL%/}/"

echo "=========================================="
echo "Food Safety Agent — Endpoint Test"
echo "=========================================="
echo ""
echo "Endpoint: $ALB_URL"
echo "Query:    \"$QUERY\""
echo ""

# Generate session ID
SESSION_ID="test-$(date +%s)-$(uuidgen | cut -c1-8)"

echo "Sending request..."
echo ""

# Make request
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST "$ALB_URL" \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"$QUERY\", \"session_id\": \"$SESSION_ID\"}" \
    2>&1 || echo "ERROR")

# Parse response
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

echo "HTTP Status: $HTTP_CODE"
echo ""

if [ "$HTTP_CODE" = "200" ]; then
    echo "✓ Request successful!"
    echo ""
    echo "Response:"
    echo "--------"
    echo "$BODY" | python -m json.tool 2>/dev/null || echo "$BODY"
    echo "--------"
    echo ""
    
    # Extract result
    RESULT=$(echo "$BODY" | python -c "import sys, json; d=json.load(sys.stdin); print(d.get('result', d.get('error', str(d))))" 2>/dev/null || echo "")
    if [ -n "$RESULT" ]; then
        echo "Result:"
        echo "$RESULT" | head -20
        if [ $(echo "$RESULT" | wc -l) -gt 20 ]; then
            echo "... (truncated)"
        fi
    fi
else
    echo "❌ Request failed!"
    echo ""
    echo "Response body:"
    echo "$BODY" | python -m json.tool 2>/dev/null || echo "$BODY"
fi

echo ""
echo "=========================================="
echo ""

# Provide debugging tips
if [ "$HTTP_CODE" != "200" ]; then
    echo "Troubleshooting:"
    echo ""
    echo "1. Check if ALB is healthy:"
    echo "   aws elbv2 describe-target-health --target-group-arn <TG-ARN> --region us-west-2"
    echo ""
    echo "2. Check Lambda logs:"
    echo "   aws logs tail /aws/lambda/food-safety-agent-proxy --follow --region us-west-2"
    echo ""
    echo "3. Verify agent is running:"
    echo "   aws agentcore describe-agent --agent-name foodsafetyagent --region us-west-2"
    echo ""
    echo "4. Test Lambda directly:"
    echo "   aws lambda invoke --function-name food-safety-agent-proxy --payload '{\"body\": \"{\\\"query\\\": \\\"test\\\"}\" }' /tmp/response.json --region us-west-2 && cat /tmp/response.json"
fi
