"""Per-city adapters that build the test-split ``AuditFrame`` (see ``frame.py``).

Each adapter owns its city's loading — the temporal split, the served model, and
the joins for geo / facility / tenure / cuisine — and emits the fixed contract the
census join and metrics engine consume. Adapters never attach census columns.
"""

from __future__ import annotations
