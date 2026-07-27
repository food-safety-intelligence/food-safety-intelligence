# Check the GitHub OIDC deploy-role trust policies

**Run in**: AWS CloudShell, signed in to account **991500268971**, region **us-west-2**.
**Why now**: the repository became **public** on 2026-07-27 so GitHub Pages would be
free. Nothing about a public repo automatically widens who can assume an AWS role,
but it is the right moment to confirm the two deploy roles trust *this repository
and nothing else*. Steps 1 and 2 are read-only.

The two roles, from the repo's Actions variables:

| Variable | Role |
|---|---|
| `WEB_DEPLOY_ROLE_ARN` | `arn:aws:iam::991500268971:role/github-web-deploy` |
| `AGENT_DEPLOY_ROLE_ARN` | `arn:aws:iam::991500268971:role/github-agent-deploy` |

---

## Step 0 — confirm you are in the right account

```bash
aws sts get-caller-identity --query Account --output text
```

Expect `991500268971`. If you get `180294210896` you are in Bella's account and the
roles below will not exist.

---

## Step 1 — print both trust policies

```bash
for role in github-web-deploy github-agent-deploy; do
  echo "===== $role ====="
  aws iam get-role --role-name "$role" \
    --query 'Role.AssumeRolePolicyDocument' --output json
done
```

Read each one against the checklist in Step 2.

---

## Step 2 — the automated check

This prints a PASS or FAIL per role and explains each verdict. Read-only.

```bash
for role in github-web-deploy github-agent-deploy; do
  aws iam get-role --role-name "$role" \
    --query 'Role.AssumeRolePolicyDocument' --output json > "/tmp/$role.json"
done

python3 - <<'PY'
import json

EXPECTED_REPO = "repo:food-safety-intelligence/food-safety-intelligence"
PROVIDER = "oidc-provider/token.actions.githubusercontent.com"

for role in ("github-web-deploy", "github-agent-deploy"):
    doc = json.load(open(f"/tmp/{role}.json"))
    print(f"\n===== {role} =====")
    problems, notes = [], []

    for stmt in doc.get("Statement", []):
        if stmt.get("Effect") != "Allow":
            continue
        principal = stmt.get("Principal", {})
        fed = principal.get("Federated", "")
        fed = fed if isinstance(fed, str) else " ".join(fed)

        # Only GitHub's OIDC provider should be able to assume these.
        if PROVIDER not in fed:
            problems.append(f"principal is not the GitHub OIDC provider: {principal}")
            continue

        cond = stmt.get("Condition", {})
        flat = {}
        for op, kv in cond.items():
            for k, v in kv.items():
                flat[k.lower()] = (op, v if isinstance(v, list) else [v])

        # (a) audience must be pinned
        aud = flat.get("token.actions.githubusercontent.com:aud")
        if not aud:
            problems.append("no `aud` condition — add StringEquals aud = sts.amazonaws.com")
        elif aud[1] != ["sts.amazonaws.com"]:
            problems.append(f"unexpected `aud`: {aud[1]}")

        # (b) subject must be pinned to THIS repo. This is the critical one.
        sub = flat.get("token.actions.githubusercontent.com:sub")
        if not sub:
            problems.append(
                "NO `sub` CONDITION — any GitHub repo on the internet can assume "
                "this role. Fix immediately (Step 3)."
            )
        else:
            op, vals = sub
            for v in vals:
                if v.strip() in ("*", "repo:*"):
                    problems.append(f"`sub` is a bare wildcard ({v!r}) — same as no condition")
                elif not v.startswith(EXPECTED_REPO):
                    problems.append(
                        f"`sub` names a DIFFERENT repo: {v!r}. If that owner/name is "
                        "now free, someone can register it and assume this role."
                    )
                elif v == f"{EXPECTED_REPO}:*":
                    notes.append(
                        f"`sub` = {v!r} ({op}). Correct and safe. Optional tightening: "
                        "the deploy workflows only run on push to main and manual "
                        "dispatch, so `:ref:refs/heads/main` would be tighter."
                    )
                else:
                    notes.append(f"`sub` = {v!r} ({op}). Correctly scoped.")

    for p in problems:
        print("  FAIL:", p)
    for n in notes:
        print("  ok:  ", n)
    if not problems:
        print("  => PASS")
PY
```

### What the verdicts mean

| Finding | Severity | Meaning |
|---|---|---|
| No `sub` condition | **Critical** | Any workflow in any GitHub repository can assume the role. Fix before anything else. |
| `sub` is `*` or `repo:*` | **Critical** | Same as having no condition. |
| `sub` names a different owner/repo | **High** | Deploys are already broken, and if that namespace is unclaimed someone can register it and assume the role. See the note below. |
| `sub` is `repo:food-safety-intelligence/food-safety-intelligence:*` | **Pass** | Correct. Optionally tighten to `main`. |
| No `aud` condition | Medium | Add `sts.amazonaws.com`. |

> **Watch for the old owner name.** This repository was transferred from
> `junxu315/food-safety-intelligence` to the organization. If either trust policy
> still says `repo:junxu315/food-safety-intelligence:*`, that is not just stale —
> GitHub frees the old namespace, so anyone who creates a repo at that path could
> mint a token matching the condition. Treat it as **High** and fix it in Step 3.

---

## Step 3 — remediation, only if Step 2 reported FAIL

> Changes the trust policy. Read the generated file before applying, and keep the
> backup so you can roll back.

Set the role you are fixing, then write the corrected policy:

```bash
ROLE=github-web-deploy   # or: github-agent-deploy

# Back up the current policy first.
aws iam get-role --role-name "$ROLE" \
  --query 'Role.AssumeRolePolicyDocument' --output json > "/tmp/$ROLE.backup.json"

cat > /tmp/trust.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::991500268971:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:food-safety-intelligence/food-safety-intelligence:*"
        }
      }
    }
  ]
}
JSON

# Read it before applying.
cat /tmp/trust.json

aws iam update-assume-role-policy --role-name "$ROLE" --policy-document file:///tmp/trust.json
```

Then re-run Step 2 to confirm it now reports PASS, and repeat for the other role.

**Tighter variant.** Both deploy workflows fire only on push to `main` or manual
dispatch, so nothing needs to assume these roles from a branch or a pull request.
To restrict to `main`, swap the `StringLike` block above for:

```json
"StringEquals": {
  "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
  "token.actions.githubusercontent.com:sub": "repo:food-safety-intelligence/food-safety-intelligence:ref:refs/heads/main"
}
```

Note this drops the separate `StringLike` block, since both conditions become exact
matches. `workflow_dispatch` from `main` still matches. Dispatching either deploy
workflow from a non-`main` branch would stop working, which is the intent.

**Rollback:**

```bash
aws iam update-assume-role-policy --role-name "$ROLE" \
  --policy-document "file:///tmp/$ROLE.backup.json"
```

---

## Step 4 — optional, confirm the deploys still work

Only if you changed a policy. Re-run a deploy from the Actions tab
(`Deploy web app` or `Deploy agent` → "Run workflow" on `main`) and confirm the
"configure AWS credentials" step still succeeds. A trust-policy mistake shows up
there as `Not authorized to perform sts:AssumeRoleWithWebIdentity`.

---

## Context worth knowing

- **Making the repo public did not, by itself, expose these roles.** A fork's pull
  request does not receive an OIDC token for the base repository, and none of the
  three AWS-credentialed workflows (`deploy-web`, `deploy-agent`, `deploy-site`)
  run on `pull_request` — they fire only on push to `main` or manual dispatch.
  `ci.yml` is the only `pull_request`-triggered workflow and it has
  `permissions: contents: read`, no OIDC and no secrets.
- **No workflow uses `pull_request_target`** and none references `secrets.*`.
- Account IDs, role ARNs, and the ALB DNS name appear in about ten tracked files
  and are now public. That was a deliberate call: they are identifiers, not
  credentials, and scrubbing them forward would leave them in git history anyway.
  A correctly scoped trust policy is what actually protects the account, which is
  why this check exists.
