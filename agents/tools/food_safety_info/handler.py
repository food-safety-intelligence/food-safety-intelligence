"""
Lambda handler: food_safety_info
--------------------------------
Answers GENERAL food-safety and foodborne-illness questions (what a pathogen is,
how common illness is, safe cooking temperatures, who is most at risk, how to
prevent it) with short, vetted facts AND a citation to an authoritative public
health source the user can click through to.

This is the educational counterpart to the restaurant-risk tools. It is NOT about
any specific establishment's score — it gives general public-health information
and verifiable links. The "local" topic is city-aware: it surfaces the ACTIVE
CITY's health department + inspection portal (Chicago, NYC, or LA).

GROUNDING & SOURCING POSTURE — read before changing this file:
  * Every fact in this file is a short paraphrase of an AUTHORITATIVE public
    health source, and every entry ships the source link it came from. The agent
    relays these vetted facts and cites the link — it must not invent statistics
    of its own. This keeps the citation TRUE: the number the user reads and the
    page the link opens are the same source.
  * Sources are restricted to a curated ALLOWED_DOMAINS allow-list (US federal
    public-health agencies, the WHO, NIH MedlinePlus, a recognised food-safety
    nonprofit, and the covered cities' local public health: Chicago / Illinois /
    Cook County + the Chicago Data Portal, NYC Health, and LA County Public
    Health). No news outlets, no blogs, no open web search — those are not
    authoritative for disease statistics and their links rot or paywall.
  * Links are stable landing pages, not search URLs. The eval harness
    (agents/eval/run_eval.py --links) resolves every URL so dead links are caught
    before they reach a user; the always-on gate checks each URL is on the
    allow-list. If you add or change a source, run the link check.
  * This tool gives information, never medical advice. Personal "what should I
    eat / is it safe for me" questions are steered to a professional — that
    boundary lives in the system prompt and the Bedrock guardrail, not here.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Disclaimer attached to every response — keeps general public-health education
# visibly distinct from both medical advice and any restaurant's risk score.
DISCLAIMER = (
    "General food-safety information from public health authorities, for education "
    "only. This is not medical advice and is not specific to any restaurant's risk "
    "score. For personal health concerns, consult a healthcare professional."
)

# The ONLY domains a citation may come from. A source URL passes if its host is
# one of these or a sub-domain of one. Adding a domain here is a deliberate
# editorial decision — keep it to authoritative public-health / government
# sources (see the module docstring).
ALLOWED_DOMAINS: frozenset[str] = frozenset(
    {
        "cdc.gov",  # US Centers for Disease Control and Prevention
        "fda.gov",  # US Food and Drug Administration
        "fsis.usda.gov",  # USDA Food Safety and Inspection Service
        "foodsafety.gov",  # HHS/USDA consumer food safety
        "who.int",  # World Health Organization
        "medlineplus.gov",  # NIH consumer health
        "fightbac.org",  # Partnership for Food Safety Education (nonprofit)
        "chicago.gov",  # Chicago Department of Public Health
        "cityofchicago.org",  # Chicago Data Portal (data.cityofchicago.org)
        "illinois.gov",  # Illinois Department of Public Health (dph.illinois.gov)
        "cookcountypublichealth.org",  # Cook County Department of Public Health
        "nyc.gov",  # NYC Department of Health and Mental Hygiene
        "lacounty.gov",  # LA County Public Health (publichealth.lacounty.gov)
    }
)

# Source catalogue: id -> (display name, URL). All URLs verified to resolve in a
# browser; a few federal pages (FSIS, FoodSafety.gov) bot-block automated GETs
# with 403 — that is reachable-but-restricted, not a dead link (see the --links
# check in the eval).
_SOURCES: dict[str, tuple[str, str]] = {
    "cdc_burden": (
        "CDC — Foodborne illness: facts & statistics",
        "https://www.cdc.gov/food-safety/data-research/facts-stats/index.html",
    ),
    "cdc_food_safety": (
        "CDC — Food Safety",
        "https://www.cdc.gov/food-safety/about/index.html",
    ),
    "cdc_foodnet": (
        "CDC — FoodNet surveillance",
        "https://www.cdc.gov/foodnet/index.html",
    ),
    "cdc_salmonella": ("CDC — Salmonella", "https://www.cdc.gov/salmonella/about/index.html"),
    "cdc_ecoli": ("CDC — E. coli", "https://www.cdc.gov/ecoli/about/index.html"),
    "cdc_listeria": ("CDC — Listeria", "https://www.cdc.gov/listeria/about/index.html"),
    "cdc_norovirus": ("CDC — Norovirus", "https://www.cdc.gov/norovirus/index.html"),
    "cdc_campylobacter": (
        "CDC — Campylobacter",
        "https://www.cdc.gov/campylobacter/about/index.html",
    ),
    "cdc_handwashing": (
        "CDC — Clean hands",
        "https://www.cdc.gov/clean-hands/about/index.html",
    ),
    "fsis_temps": (
        "USDA FSIS — Safe minimum internal temperature chart",
        "https://www.fsis.usda.gov/food-safety/safe-food-handling-and-preparation/food-safety-basics/safe-temperature-chart",
    ),
    "foodsafety_steps": (
        "FoodSafety.gov — 4 steps to food safety",
        "https://www.foodsafety.gov/keep-food-safe/4-steps-to-food-safety",
    ),
    "foodsafety_atrisk": (
        "FoodSafety.gov — People at risk",
        "https://www.foodsafety.gov/food-poisoning/people-at-risk",
    ),
    "foodsafety_recalls": (
        "FoodSafety.gov — Recalls & outbreaks",
        "https://www.foodsafety.gov/recalls-and-outbreaks",
    ),
    "fda_recalls": (
        "FDA — Recalls, outbreaks & emergencies",
        "https://www.fda.gov/food/recalls-outbreaks-emergencies",
    ),
    "who_food_safety": (
        "WHO — Food safety fact sheet",
        "https://www.who.int/news-room/fact-sheets/detail/food-safety",
    ),
    "medlineplus": (
        "MedlinePlus (NIH) — Foodborne illness",
        "https://medlineplus.gov/foodborneillness.html",
    ),
    "fightbac": (
        "Partnership for Food Safety Education — Core Four practices",
        "https://www.fightbac.org/food-safety-basics/the-core-four-practices/",
    ),
    "chicago_cdph": (
        "Chicago Department of Public Health — Food safety",
        "https://www.chicago.gov/city/en/depts/cdph/provdrs/food_safety.html",
    ),
    "chicago_data": (
        "Chicago Data Portal — Food Inspections",
        "https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5",
    ),
    "illinois_dph": (
        "Illinois Department of Public Health — Food safety",
        "https://dph.illinois.gov/topics-services/food-safety.html",
    ),
    "cook_county": (
        "Cook County Department of Public Health",
        "https://cookcountypublichealth.org/",
    ),
    "nyc_doh": (
        "NYC Health — Restaurant grades & inspection results",
        "https://www.nyc.gov/site/doh/services/restaurant-grades.page",
    ),
    "la_eh": (
        "LA County Public Health — Restaurant & market inspections",
        "https://publichealth.lacounty.gov/eh/inspection-and-reports/restaurant-and-market-inspections.htm",
    ),
}

# Topic registry: key -> (title, vetted summary, [source ids]). The summary is
# what the agent relays; statistics in it are paraphrased from the cited source.
_TOPICS: dict[str, tuple[str, str, list[str]]] = {
    "overview": (
        "Foodborne illness in the United States",
        "The CDC estimates that each year roughly 1 in 6 Americans (about 48 million "
        "people) get sick, 128,000 are hospitalised, and 3,000 die from foodborne "
        "diseases. Most cases come from a handful of common germs and are preventable "
        "with safe food handling.",
        ["cdc_burden", "cdc_food_safety", "medlineplus"],
    ),
    "symptoms": (
        "Symptoms of foodborne illness",
        "Common symptoms include upset stomach, abdominal cramps, nausea, vomiting, "
        "diarrhoea, and fever, usually starting hours to a few days after eating "
        "contaminated food. Most people recover on their own, but severe signs — high "
        "fever, blood in the stool, prolonged vomiting, or dehydration — warrant "
        "medical care.",
        ["medlineplus", "cdc_food_safety"],
    ),
    "salmonella": (
        "Salmonella",
        "Salmonella causes about 1.35 million infections in the US each year and is a "
        "leading cause of foodborne hospitalisations and deaths. It is commonly linked "
        "to poultry, eggs, and raw produce. Thorough cooking and avoiding "
        "cross-contamination lower the risk.",
        ["cdc_salmonella"],
    ),
    "ecoli": (
        "E. coli (STEC)",
        "Some E. coli strains (Shiga toxin-producing, or STEC) cause severe illness, "
        "and a few cases progress to haemolytic uraemic syndrome — a type of kidney "
        "failure — especially in young children. Sources include undercooked ground "
        "beef, raw produce, and unpasteurised milk or juice.",
        ["cdc_ecoli"],
    ),
    "listeria": (
        "Listeria",
        "Listeria causes an estimated 1,600 illnesses and 260 deaths in the US each "
        "year and is especially dangerous for pregnant people, newborns, adults 65 and "
        "older, and people with weakened immune systems. It is linked to deli meats, "
        "soft cheeses, and refrigerated smoked fish, and can grow even at fridge "
        "temperatures.",
        ["cdc_listeria", "foodsafety_atrisk"],
    ),
    "norovirus": (
        "Norovirus",
        "Norovirus is the leading cause of foodborne illness in the US (about 58% of "
        "domestically acquired cases). It is very contagious and spreads through "
        "contaminated food or surfaces and from person to person; infected food "
        "handlers are a frequent source.",
        ["cdc_norovirus"],
    ),
    "campylobacter": (
        "Campylobacter",
        "Campylobacter is one of the most common bacterial causes of diarrhoeal "
        "illness. It is most often linked to raw or undercooked poultry and to raw "
        "(unpasteurised) milk.",
        ["cdc_campylobacter"],
    ),
    "cooking_temperatures": (
        "Safe cooking temperatures",
        "Use a food thermometer: cook poultry to 165°F (74°C), ground meats to 160°F "
        "(71°C), and steaks, chops, and roasts to 145°F (63°C) with a 3-minute rest. "
        "Keep food out of the 'Danger Zone' of 40–140°F (4–60°C), where bacteria "
        "multiply fastest.",
        ["fsis_temps", "foodsafety_steps"],
    ),
    "prevention": (
        "Preventing foodborne illness",
        "The four core steps are Clean, Separate, Cook, and Chill: wash hands and "
        "surfaces often, keep raw meat away from ready-to-eat food, cook to safe "
        "temperatures, and refrigerate promptly. Handwashing alone prevents a large "
        "share of illness.",
        ["foodsafety_steps", "fightbac", "cdc_handwashing"],
    ),
    "at_risk_groups": (
        "Who is most at risk",
        "Pregnant people, children under 5, adults 65 and older, and people with "
        "weakened immune systems are more likely to get seriously ill from foodborne "
        "germs and should take extra care with higher-risk foods.",
        ["foodsafety_atrisk", "cdc_listeria"],
    ),
    "recalls": (
        "Food recalls and outbreak alerts",
        "Current US food recalls and outbreak investigations are published by the FDA "
        "and aggregated on FoodSafety.gov. Check them to see if a product in your "
        "kitchen has been recalled.",
        ["fda_recalls", "foodsafety_recalls"],
    ),
    "global": (
        "Foodborne illness worldwide",
        "The WHO estimates that about 600 million people — almost 1 in 10 worldwide — "
        "fall ill from contaminated food each year, and 420,000 die. Children under 5 "
        "carry a disproportionate share of the burden.",
        ["who_food_safety"],
    ),
    "surveillance": (
        "How foodborne illness is tracked",
        "In the US, the CDC's FoodNet network monitors lab-confirmed infections from "
        "common foodborne germs across sentinel sites, which is how national trends and "
        "estimates are produced.",
        ["cdc_foodnet", "cdc_burden"],
    ),
}

# The "local" topic — how the ACTIVE CITY inspects restaurants and where to find
# its records. One entry per covered city; the handler picks the active city's, so
# an NYC user only ever sees NYC sources, an LA user LA sources, etc. Each summary
# also states that city's GRADE FRAMING (letter grades + direction), so it doubles
# as the answer to "how does this city's grading work?".
_LOCAL_TOPICS: dict[str, tuple[str, str, list[str]]] = {
    "chicago": (
        "Food safety in Chicago",
        "Chicago food establishments are inspected by the Chicago Department of Public "
        "Health and each inspection is recorded as Pass, Pass with Conditions, or Fail "
        "with cited violation codes (there is no letter grade). Results are public on "
        "the Chicago Data Portal — the dataset behind this project's risk scores. "
        "Illinois DPH and Cook County DPH also publish food-safety guidance.",
        ["chicago_cdph", "chicago_data", "illinois_dph", "cook_county"],
    ),
    "nyc": (
        "Food safety in New York City",
        "New York City restaurants are inspected by the NYC Health Department, which "
        "assigns a letter grade — A, B, or C — from an inspection points score where "
        "FEWER points is cleaner (A is the top grade). Grades and full inspection "
        "results are public.",
        ["nyc_doh"],
    ),
    "la": (
        "Food safety in Los Angeles",
        "Restaurants in Los Angeles County are inspected by the LA County Department of "
        "Public Health, which posts a letter grade — A, B, or C — from a 0-100 score "
        "where a HIGHER score is cleaner (A is 90-100, the opposite direction to NYC). "
        "Inspection results are public.",
        ["la_eh"],
    ),
}

# Free-text keyword -> topic key. Order matters only for readability; matching
# scans the whole query, so the most specific keys are listed with their own
# synonyms. Generic food-safety phrasing falls through to the default below.
_SYNONYMS: dict[str, str] = {
    "salmonella": "salmonella",
    "e. coli": "ecoli",
    "e.coli": "ecoli",
    "e coli": "ecoli",
    "ecoli": "ecoli",
    "stec": "ecoli",
    "o157": "ecoli",
    "listeria": "listeria",
    "listeriosis": "listeria",
    "norovirus": "norovirus",
    "norwalk": "norovirus",
    "stomach bug": "norovirus",
    "campylobacter": "campylobacter",
    "temperature": "cooking_temperatures",
    "thermometer": "cooking_temperatures",
    "undercook": "cooking_temperatures",
    "danger zone": "cooking_temperatures",
    "how hot": "cooking_temperatures",
    "prevent": "prevention",
    "avoid getting": "prevention",
    "handwash": "prevention",
    "wash hands": "prevention",
    "cross-contamination": "prevention",
    "cross contamination": "prevention",
    "four steps": "prevention",
    "pregnan": "at_risk_groups",
    "immunocompromised": "at_risk_groups",
    "weak immune": "at_risk_groups",
    "weakened immune": "at_risk_groups",
    "at risk": "at_risk_groups",
    "high risk group": "at_risk_groups",
    "elderly": "at_risk_groups",
    "recall": "recalls",
    "outbreak": "recalls",
    "global": "global",
    "worldwide": "global",
    "world health": "global",
    "foodnet": "surveillance",
    "surveillance": "surveillance",
    "how is it tracked": "surveillance",
    # Local inspection regime / where to find records -> the ACTIVE CITY's sources.
    "chicago": "local",
    "illinois": "local",
    "cook county": "local",
    "new york": "local",
    "nyc": "local",
    "los angeles": "local",
    "la county": "local",
    "data portal": "local",
    "inspection data": "local",
    "letter grade": "local",
    "restaurant grade": "local",
    "grading": "local",
    "who inspects": "local",
    "how are restaurants inspected": "local",
    "how often are restaurants inspected": "local",
    "inspection frequency": "local",
    "symptom": "symptoms",
    "nausea": "symptoms",
    "vomit": "symptoms",
    "diarrhea": "symptoms",
    "diarrhoea": "symptoms",
    "how common": "overview",
    "how many": "overview",
    "statistic": "overview",
    "how often": "overview",
    "prevalence": "overview",
    "burden": "overview",
}

# When a query is clearly food-safety related but matches no specific topic, give
# the headline picture plus how to prevent it.
_DEFAULT_TOPICS = ["overview", "prevention"]

# Cap entries per response so the agent gets a focused, citable set, not a wall.
_MAX_TOPICS = 4


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    """
    Lambda entry point.

    Input event schema:
    {
        "query":  str,              # the user's general food-safety question
        "topics": list[str] | None  # optional explicit subset of topic keys
    }

    Returns:
    {
        "query": str,
        "topics": list[str],
        "info": [{topic, title, summary, sources: [{name, url}]}],
        "disclaimer": str
    }
    """
    query: str = (event.get("query") or "").strip()
    # Which city's local sources to surface for the "local" topic (multi-city).
    # Default Chicago; the entrypoint passes the active city.
    city = (event.get("city") or "chicago").strip().lower()
    if city not in _LOCAL_TOPICS:
        city = "chicago"
    topics = _resolve_topics(event.get("topics"), query)

    return {
        "query": query,
        "city": city,
        "topics": topics,
        "info": [_entry(key, city) for key in topics],
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Topic resolution
# ---------------------------------------------------------------------------


def _resolve_topics(raw: Any, query: str) -> list[str]:
    """Pick topic keys from an explicit list or by matching the query text.

    Explicit `topics` win when any are valid. Otherwise scan the query for known
    synonyms (longest match first so "e. coli" beats a stray "coli"). Falls back
    to the overview + prevention default when nothing matches.
    """
    if raw:
        if isinstance(raw, str):
            raw = [raw]
        keep = [
            t.strip().lower()
            for t in raw
            if t.strip().lower() in _TOPICS or t.strip().lower() == "local"
        ]
        if keep:
            return keep[:_MAX_TOPICS]

    text = query.lower()
    matched: list[str] = []
    for phrase in sorted(_SYNONYMS, key=len, reverse=True):
        if phrase in text:
            key = _SYNONYMS[phrase]
            if key not in matched:
                matched.append(key)

    return (matched or _DEFAULT_TOPICS)[:_MAX_TOPICS]


def _entry(key: str, city: str = "chicago") -> dict[str, Any]:
    """Build one topic entry: title, vetted summary, and its citation links.

    The "local" topic resolves to the ACTIVE CITY's inspection regime + sources, so
    an NYC user gets NYC sources and framing, an LA user LA's, etc.
    """
    title, summary, source_ids = _LOCAL_TOPICS[city] if key == "local" else _TOPICS[key]
    return {
        "topic": key,
        "title": title,
        "summary": summary,
        "sources": [{"name": _SOURCES[s][0], "url": _SOURCES[s][1]} for s in source_ids],
    }


# ---------------------------------------------------------------------------
# Source allow-list check (used here and by the eval harness)
# ---------------------------------------------------------------------------


def is_allowed_url(url: str) -> bool:
    """True if the URL is https and its host is on (or under) ALLOWED_DOMAINS."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)


def all_source_urls() -> list[str]:
    """Every citation URL in the catalogue (for the eval link check)."""
    return [url for _name, url in _SOURCES.values()]
