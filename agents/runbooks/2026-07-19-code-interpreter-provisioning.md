# Provisioning: AgentCore Code Interpreter + chart artifact bucket

Runbook for the chat agent's **data-visualization** capability. Everything here runs
**in Deepak's account (991500268971)** — run it in **AWS CloudShell signed in as Deepak's
IAM user**, or with his creds exported. Nothing here touches Bella's account.

What it creates:
1. A **private S3 bucket** for generated chart PNGs (7-day TTL, presigned-URL access only —
   no public access, no CloudFront).
2. An **isolated (network-off) Code Interpreter** the agent tool runs snippets in.
3. An **IAM policy** on the AgentCore **runtime execution role** granting the two above.

> Verify-before-trust: a few command/parameter names for the newer `bedrock-agentcore`
> control-plane API can drift between CLI/boto3 versions. Where noted, run the small
> introspection helper first and adjust names to what your version prints. The S3 and IAM
> commands are stable.

---

## 0. Set variables

```bash
# --- confirm these three before running anything ---
export REGION="us-west-2"                       # the region the AgentCore runtime lives in
export CHART_BUCKET="fsi-agent-charts-991500268971"   # new private bucket name (globally unique)
export EXEC_ROLE_NAME="AgentCore-foodsafety-defa-ApplicationAgentFoodsafet-wMqqRqVPcPK3"                         # the runtime's execution role NAME (discover below)

export ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
echo "acct=$ACCOUNT region=$REGION bucket=$CHART_BUCKET"   # acct should be 991500268971
```

Discover the runtime execution role if you don't have it handy:

```bash
# List runtimes, find the food-safety agent, read its execution role ARN.
aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
  --query 'agentRuntimes[].{name:agentRuntimeName,id:agentRuntimeId}' --output table

# Then (fill in the id):
aws bedrock-agentcore-control get-agent-runtime --region "$REGION" \
  --agent-runtime-id "foodsafety_foodsafetyagent-4UtF42EBno" --query 'roleArn' --output text
# -> arn:aws:iam::991500268971:role/<THIS_IS_EXEC_ROLE_NAME>
```
Set `EXEC_ROLE_NAME` to the role name (the part after `role/`).

---

## 1. Private chart bucket (7-day TTL, no public access)

```bash
# create-bucket: for us-east-1 REMOVE the --create-bucket-configuration line entirely.
aws s3api create-bucket --bucket "$CHART_BUCKET" --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION"

# lock it down completely (access is only ever via presigned URLs)
aws s3api put-public-access-block --bucket "$CHART_BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# auto-expire charts after 7 days
aws s3api put-bucket-lifecycle-configuration --bucket "$CHART_BUCKET" \
  --lifecycle-configuration '{"Rules":[{"ID":"expire-charts","Filter":{"Prefix":"charts/"},"Status":"Enabled","Expiration":{"Days":7}}]}'

# (optional) default server-side encryption
aws s3api put-bucket-encryption --bucket "$CHART_BUCKET" \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

---

## 2. Isolated Code Interpreter (network OFF)

We want a **custom** interpreter pinned to network-isolated mode so model-written code has
**no egress**. (The built-in default `aws.codeinterpreter.v1` is quicker but confirm its
network mode before relying on it for untrusted code.)

First print the exact parameter names your boto3 expects, then create:

```bash
python3 - <<'PY'
import boto3
c = boto3.client("bedrock-agentcore-control")
op = c.meta.service_model.operation_model("CreateCodeInterpreter")
print("INPUT PARAMS:", list(op.input_shape.members.keys()))
for name, shape in op.input_shape.members.items():
    print(" -", name, ":", getattr(shape, "type_name", "?"),
          list(getattr(shape, "members", {}).keys()) if shape.type_name == "structure" else "")
PY
```

Then create it. `networkMode` is an enum — valid values are **`SANDBOX`** (managed,
no outbound network — use this), `ISOLATED` (also no network, stricter), `VPC` (runs
in your VPC, needs a `vpcConfig` — gives it network access, NOT what we want), and
`PUBLIC` (full egress). Do NOT pass `vpcConfig` as the mode; that's a field name, not
a value. `executionRoleArn` is optional and can be omitted for SANDBOX.

```bash
python3 - <<PY
import boto3, os
c = boto3.client("bedrock-agentcore-control", region_name=os.environ["REGION"])
resp = c.create_code_interpreter(
    name="fsi_agent_chart_sandbox",
    description="Isolated no-egress sandbox for the food-safety chat agent chart tool",
    networkConfiguration={"networkMode": "SANDBOX"},   # SANDBOX = no outbound network
)
print("CODE_INTERPRETER_ID:", resp.get("codeInterpreterId") or resp)
PY
```

Save the printed **`CODE_INTERPRETER_ID`** — the runtime needs it as an env var (step 4).

---

## 3. Grant the runtime role: Code Interpreter + chart-bucket access

```bash
cat > /tmp/fsi-chart-policy.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AgentCoreCodeInterpreter",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:StartCodeInterpreterSession",
        "bedrock-agentcore:InvokeCodeInterpreter",
        "bedrock-agentcore:StopCodeInterpreterSession",
        "bedrock-agentcore:GetCodeInterpreterSession",
        "bedrock-agentcore:ListCodeInterpreterSessions"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ChartArtifacts",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::${CHART_BUCKET}/charts/*"
    }
  ]
}
JSON

aws iam put-role-policy \
  --role-name "$EXEC_ROLE_NAME" \
  --policy-name "fsi-chart-visualization" \
  --policy-document file:///tmp/fsi-chart-policy.json
```

> Tighter option: scope the `AgentCoreCodeInterpreter` `Resource` from `"*"` to
> `"arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT}:code-interpreter/${CODE_INTERPRETER_ID}"`
> plus its `.../code-interpreter/${CODE_INTERPRETER_ID}/session/*`. Start with `"*"` if the
> ARN shape errors, then tighten once confirmed.

---

## 4. Hand these values to the runtime — NOT a CloudShell step

These are runtime **environment variables**, not shell commands (don't paste them
into a terminal). Add them to the runtime's env config in
**`agentcore-deploy/agentcore/agentcore.json`** → `runtimes[0].envVars` (alongside
`DATA_BUCKET`, the guardrail vars, etc.); the CDK deploy (`deploy-agent.yml` on
merge to `main`) applies them on the next deploy:

```jsonc
{ "name": "FSI_SANDBOX_USE_STUB",    "value": "false" }              // REQUIRED: real execution (default true = stub)
{ "name": "FSI_CHART_REGION",        "value": "us-west-2" }          // region of the Code Interpreter + charts bucket
{ "name": "FSI_CHART_BUCKET",        "value": "<CHART_BUCKET>" }
{ "name": "FSI_CODE_INTERPRETER_ID", "value": "<CODE_INTERPRETER_ID>" }
// optional: FSI_CHART_URL_TTL_SECONDS = 3600 (presigned URL lifetime; default 1h,
//           and a presigned URL can't outlive the runtime role's ~1h STS session)
```

`FSI_CHART_REGION` matters because the runtime's `AWS_REGION` is **us-east-1** (the
Bedrock model + the data bucket), but the sandbox and charts bucket live in the
runtime's own region (**us-west-2**) — without it the tool would look in the wrong
region and fail. Without `FSI_SANDBOX_USE_STUB=false` the tool stays in stub mode
and returns a placeholder chart; setting it (with the bucket + interpreter
provisioned above) is what switches the deployed agent to real charts.

---

## 5. Verify

```bash
# bucket exists, is private, has the TTL rule
aws s3api get-public-access-block --bucket "$CHART_BUCKET"
aws s3api get-bucket-lifecycle-configuration --bucket "$CHART_BUCKET"

# policy attached to the role
aws iam get-role-policy --role-name "$EXEC_ROLE_NAME" --policy-name "fsi-chart-visualization"

# interpreter is READY
aws bedrock-agentcore-control list-code-interpreters --region "$REGION" \
  --query 'codeInterpreters[].{id:codeInterpreterId,status:status,net:networkConfiguration}' --output table
```

## Teardown (if abandoning the feature)

```bash
aws iam delete-role-policy --role-name "$EXEC_ROLE_NAME" --policy-name "fsi-chart-visualization"
aws bedrock-agentcore-control delete-code-interpreter --region "$REGION" --code-interpreter-id "<CODE_INTERPRETER_ID>"
aws s3 rm "s3://$CHART_BUCKET" --recursive && aws s3api delete-bucket --bucket "$CHART_BUCKET" --region "$REGION"
```
