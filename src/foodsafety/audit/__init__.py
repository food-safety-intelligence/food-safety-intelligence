"""Fairness / ethics audit for the food-safety risk models.

Audit-only tooling. Nothing in this package is ever a model feature: the census
demographic join exists to *measure* disparate impact, never to predict (decisions
0004 / 0005). The package operates on a city-agnostic ``AuditFrame`` (see
``frame.py``) produced by a per-city adapter, so adding a city is one adapter, not
a rewrite. See ``README.md`` for the full design.
"""

from __future__ import annotations
