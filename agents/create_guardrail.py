"""
Create the Food Safety agent's Bedrock Guardrail.

Run once (by someone with `bedrock:CreateGuardrail` permission) to provision the
platform-level guardrail the agent attaches to. Two of its policies apply to
input/output text automatically, independently of whether the model follows the
system prompt:

  - Denied topics — PERSONALISED medical advice and legal advice only. There is
    deliberately NO catch-all "off-topic" topic: a negatively-defined "anything
    not about food safety" topic makes Bedrock's classifier over-match and block
    legitimate food-safety queries. Off-topic requests (recipes, other cities,
    chit-chat) are declined by the system prompt instead.
  - Denied topics — genuinely off-topic requests (recipes, other-city
    restaurant lookups, meal planning, chit-chat) plus PERSONALISED medical and
    legal advice. General factual food-safety education (answered with cited
    public health sources) is deliberately NOT denied — it is in scope.
  - Prompt-attack filter — resists "ignore your instructions" style injection.

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
# cities it covers (Chicago, New York City, and Los Angeles) and (B) general
# food-safety / foodborne-illness education with cited public health sources. The
# deny topics below must NOT block job B, so they are scoped to genuinely
# off-topic requests and to *personalised* medical advice only — general factual
# food-safety education is allowed.
_DENIED_TOPICS = [
    {
        "name": "OffTopicNonFoodSafety",
        "definition": (
            "Requests neither about food-safety risk for Chicago, New York City, or "
            "Los Angeles establishments nor general food safety or foodborne illness "
            "— e.g. recipes, cooking, meal planning, restaurants in cities we don't "
            "cover, or unrelated chat."
        ),
        "examples": [
            "Give me a recipe for deep dish pizza.",
            "Find safe sushi in Houston.",
            "What should I cook for dinner tonight?",
            "Plan a week of healthy meals for me.",
            "Tell me a joke.",
        ],
        "type": "DENY",
    },
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
    """The id of the guardrail named GUARDRAIL_NAME, if one already exists."""
    for g in client.list_guardrails().get("guardrails", []):
        if g.get("name") == GUARDRAIL_NAME:
            return g["id"]
    return None


def create() -> tuple[str, str, bool]:
    """Create the guardrail (or update it in place if the name already exists), then
    publish a new immutable version. Returns (id, version, updated). Idempotent — a
    re-run adopts the existing guardrail so the agent's wired id is unchanged (only
    the version bumps), instead of failing on the unique-name constraint."""
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("bedrock", region_name=region)

    existing = _existing_id(client)
    if existing:
        # Adopt the existing guardrail: overwrite its working draft with the current
        # policy (adds LA to scope), keeping the same id so no re-wire is needed.
        client.update_guardrail(guardrailIdentifier=existing, name=GUARDRAIL_NAME, **_POLICY)
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
