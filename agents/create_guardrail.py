"""
Create the Food Safety agent's Bedrock Guardrail.

Run once (by someone with `bedrock:CreateGuardrail` permission) to provision the
platform-level guardrail the agent attaches to. Two of its policies apply to
input/output text automatically, independently of whether the model follows the
system prompt:

  - Denied topics — PERSONALISED medical advice and legal advice only. There is
    deliberately NO catch-all "off-topic" topic: a negatively-defined "anything
    not about food safety" topic makes Bedrock's classifier over-match — an earlier
    broad version blocked ~100% of queries, including core risk lookups (commit
    9c92ce7). Off-topic requests (recipes, other cities, chit-chat) are declined by
    the system prompt instead, which the eval's off-topic/other-city cases verify.
    General factual food-safety education (with cited public-health sources) is in
    scope and must NOT be blocked.
  - Prompt-attack filter — resists "ignore your instructions" style injection.

  NOTE: decision record 0012 still describes an "OffTopicNonFoodSafety" guardrail
  topic (re-scoped) as surviving — that text predates the 9c92ce7 removal and is
  stale. The live guardrail (verified 2026-07-04: only PersonalisedMedicalAdvice +
  LegalAdvice) reflects the removal; this file now matches it. Update 0012 to record
  the removal + the over-blocking reason.

The contextual-grounding + relevance policy is configured below but is NOT active
as the agent is wired: Strands' BedrockModel does not tag the tool outputs as
grounding sources and per-message grounding is off, so this policy has no
grounding source to score a response against and will not block fabricated
scores. Anti-fabrication therefore relies on the system prompt's rules, not on
this guardrail. The policy is kept so it starts working if a grounding source is
wired in later.

Then wire the printed id + version into the agent via env vars (see
`entrypoint.py` / `run_local.py` `_guardrail_kwargs`):

    export FSI_BEDROCK_GUARDRAIL_ID=...
    export FSI_BEDROCK_GUARDRAIL_VERSION=...

Usage:
    python agents/create_guardrail.py            # create + publish a version
    AWS_REGION=us-east-1 python agents/create_guardrail.py
"""

from __future__ import annotations

import os

import boto3

GUARDRAIL_NAME = "food-safety-agent"

_BLOCK_MESSAGE = (
    "I can't help with that. I can look up a Chicago, New York City, or Los "
    "Angeles food establishment's predicted food-safety risk, or answer a general "
    "food-safety question with a cited public health source — would you like me to?"
)

# Topics the agent must refuse. Bedrock matches on the definition + examples.
#
# Scope reminder: the agent does TWO jobs — (A) restaurant risk signals for the
# cities it covers (Chicago, New York City, Los Angeles) and (B) general food-safety
# / foodborne-illness education with cited public health sources. Only *personalised*
# medical advice and legal advice are denied here; general factual food-safety
# education is allowed. Off-topic requests (recipes, other cities, chit-chat) are
# NOT a guardrail topic — a negative catch-all over-matches and blocks legitimate
# queries (see the module docstring) — so the system prompt declines them instead.
_DENIED_TOPICS = [
    {
        "name": "PersonalisedMedicalAdvice",
        "definition": (
            "Personalised medical advice for a specific person — diagnosis, "
            "treatment or medication, or whether a food is safe given their "
            "health condition. General factual food-safety education is allowed."
        ),
        "examples": [
            "Is it safe for ME to eat here with my weak immune system?",
            "Do I have food poisoning, and what medicine should I take?",
            "I'm pregnant — tell me exactly what I can and cannot eat.",
        ],
        "type": "DENY",
    },
    {
        "name": "LegalAdvice",
        "definition": "Providing legal advice, liability opinions, or legal interpretation.",
        "examples": [
            "Can I sue this restaurant if I get sick?",
        ],
        "type": "DENY",
    },
]


# The full policy, shared by create and update so a re-run can't drift.
_DESCRIPTION = (
    "Food Safety agent (Chicago + NYC + LA): denied off-topic/medical/legal "
    "topics, contextual grounding + relevance, and prompt-attack filtering."
)
_POLICY = {
    "topicPolicyConfig": {"topicsConfig": _DENIED_TOPICS},
    "contentPolicyConfig": {
        # PROMPT_ATTACK only supports an input strength (output must be NONE).
        "filtersConfig": [
            {"type": "PROMPT_ATTACK", "inputStrength": "HIGH", "outputStrength": "NONE"},
        ]
    },
    "contextualGroundingPolicyConfig": {
        "filtersConfig": [
            {"type": "GROUNDING", "threshold": 0.7},
            {"type": "RELEVANCE", "threshold": 0.7},
        ]
    },
    "blockedInputMessaging": _BLOCK_MESSAGE,
    "blockedOutputsMessaging": _BLOCK_MESSAGE,
}


def _existing_id(client) -> str | None:
    """The id of the guardrail named GUARDRAIL_NAME, if one already exists.

    Pages through list_guardrails: the response is page-limited, and Bedrock does
    NOT enforce unique guardrail names — so missing the guardrail on a single page
    would create a duplicate on the next run and break idempotency."""
    token: str | None = None
    while True:
        resp = client.list_guardrails(**({"nextToken": token} if token else {}))
        for g in resp.get("guardrails", []):
            if g.get("name") == GUARDRAIL_NAME:
                return g["id"]
        token = resp.get("nextToken")
        if not token:
            return None


def create() -> tuple[str, str, bool]:
    """Create the guardrail (or update it in place if the name already exists), then
    publish a new immutable version. Returns (id, version, updated). Idempotent — a
    re-run adopts the existing guardrail so the agent's wired id is unchanged (only
    the version bumps), instead of creating a duplicate guardrail each run."""
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("bedrock", region_name=region)

    existing = _existing_id(client)
    if existing:
        # Adopt the existing guardrail: overwrite its working draft with the current
        # policy (adds LA to scope), keeping the same id so no re-wire is needed.
        client.update_guardrail(
            guardrailIdentifier=existing,
            name=GUARDRAIL_NAME,
            description=_DESCRIPTION,
            **_POLICY,
        )
        guardrail_id = existing
    else:
        guardrail_id = client.create_guardrail(
            name=GUARDRAIL_NAME, description=_DESCRIPTION, **_POLICY
        )["guardrailId"]

    # create/update leaves the working copy as DRAFT; publish an immutable numbered
    # version to pin the agent to.
    version = client.create_guardrail_version(guardrailIdentifier=guardrail_id)["version"]
    return guardrail_id, version, bool(existing)


def main() -> None:
    guardrail_id, version, updated = create()
    verb = "Updated" if updated else "Created"
    print(f"{verb} guardrail '{GUARDRAIL_NAME}': id={guardrail_id} version={version}\n")
    print("Wire it into the agent:")
    print(f"    export FSI_BEDROCK_GUARDRAIL_ID={guardrail_id}")
    print(f"    export FSI_BEDROCK_GUARDRAIL_VERSION={version}")


if __name__ == "__main__":
    main()
