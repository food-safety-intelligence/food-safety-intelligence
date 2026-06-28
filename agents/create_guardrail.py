"""
Create the Food Safety agent's Bedrock Guardrail.

Run once (by someone with `bedrock:CreateGuardrail` permission) to provision the
platform-level guardrail the agent attaches to. Two of its policies apply to
input/output text automatically, independently of whether the model follows the
system prompt:

  - Denied topics — off-topic / non-Chicago-food requests, plus medical and
    legal advice (the agent gives a risk signal, not advice).
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
    "I can only help with predicted food-safety risk for food establishments in "
    "Chicago. I can't help with that request."
)

# Topics the agent must refuse. Bedrock matches on the definition + examples.
_DENIED_TOPICS = [
    {
        "name": "NonChicagoFoodSafety",
        "definition": (
            "Any request not about predicted food-safety risk for food "
            "establishments in Chicago — including recipes, cooking or food "
            "preparation, nutrition, restaurants in other cities, and general "
            "conversation unrelated to Chicago food-establishment safety."
        ),
        "examples": [
            "Give me a recipe for deep dish pizza.",
            "Find safe sushi in New York.",
            "What should I cook for dinner tonight?",
            "Tell me a joke.",
        ],
        "type": "DENY",
    },
    {
        "name": "MedicalOrHealthAdvice",
        "definition": (
            "Providing medical, dietary, or health advice, diagnoses, or treatment recommendations."
        ),
        "examples": [
            "Is it safe for me to eat here with a weak immune system?",
            "What should I eat to avoid food poisoning?",
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
