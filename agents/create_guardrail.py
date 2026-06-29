"""
Create the Food Safety agent's Bedrock Guardrail.

Run once (by someone with `bedrock:CreateGuardrail` permission) to provision the
platform-level guardrail the agent attaches to. Two of its policies apply to
input/output text automatically, independently of whether the model follows the
system prompt:

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
    "I can help with predicted food-safety risk for Chicago food establishments "
    "and with general food-safety information from public health sources. I can't "
    "help with that request."
)

# Topics the agent must refuse. Bedrock matches on the definition + examples.
#
# Scope reminder: the agent does TWO jobs — (A) Chicago restaurant risk signals
# and (B) general food-safety / foodborne-illness education with cited public
# health sources. The deny topics below must NOT block job B, so they are scoped
# to genuinely off-topic requests and to *personalised* medical advice only —
# general factual food-safety education is allowed.
_DENIED_TOPICS = [
    {
        "name": "OffTopicNonFoodSafety",
        "definition": (
            "Requests neither about food-safety risk for Chicago establishments "
            "nor general food safety or foodborne illness — e.g. recipes, "
            "cooking, meal planning, other-city restaurants, or unrelated chat."
        ),
        "examples": [
            "Give me a recipe for deep dish pizza.",
            "Find safe sushi in New York.",
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


def create() -> tuple[str, str]:
    """Create the guardrail and publish a numbered version. Returns (id, version)."""
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("bedrock", region_name=region)

    created = client.create_guardrail(
        name=GUARDRAIL_NAME,
        description=(
            "Food Safety Chicago agent: denied off-topic/medical/legal topics, "
            "contextual grounding + relevance, and prompt-attack filtering."
        ),
        topicPolicyConfig={"topicsConfig": _DENIED_TOPICS},
        contentPolicyConfig={
            # PROMPT_ATTACK only supports an input strength (output must be NONE).
            "filtersConfig": [
                {"type": "PROMPT_ATTACK", "inputStrength": "HIGH", "outputStrength": "NONE"},
            ]
        },
        contextualGroundingPolicyConfig={
            "filtersConfig": [
                {"type": "GROUNDING", "threshold": 0.7},
                {"type": "RELEVANCE", "threshold": 0.7},
            ]
        },
        blockedInputMessaging=_BLOCK_MESSAGE,
        blockedOutputsMessaging=_BLOCK_MESSAGE,
    )
    guardrail_id = created["guardrailId"]

    # create_guardrail leaves the working copy as DRAFT; publish an immutable
    # numbered version to pin the agent to.
    version = client.create_guardrail_version(guardrailIdentifier=guardrail_id)["version"]
    return guardrail_id, version


def main() -> None:
    guardrail_id, version = create()
    print(f"Created guardrail '{GUARDRAIL_NAME}': id={guardrail_id} version={version}\n")
    print("Wire it into the agent:")
    print(f"    export FSI_BEDROCK_GUARDRAIL_ID={guardrail_id}")
    print(f"    export FSI_BEDROCK_GUARDRAIL_VERSION={version}")


if __name__ == "__main__":
    main()
