"""Normalize every notebook in `notebooks/` so each cell has the `id` field
that nbformat 5.1.4+ requires.

Notebooks created by old Jupyter versions (pre-5.1.4) lack per-cell IDs.
Modern nbformat auto-fixes them in memory but warns about the on-disk file —
that's the `MissingIDFieldWarning` you see during `git add`. Reading and
rewriting persists the auto-generated IDs and silences the warning at the
source.

Safe to run any time. Idempotent — re-runs are a no-op on already-clean
notebooks. Does not change cell outputs (nbstripout handles those on commit).

Run:
    /Users/jun/anaconda3/bin/python scripts/normalize_notebooks.py
"""

from __future__ import annotations

from pathlib import Path

import nbformat

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTEBOOKS_DIR = REPO_ROOT / "notebooks"


def main() -> None:
    paths = sorted(NOTEBOOKS_DIR.glob("*.ipynb"))
    if not paths:
        print(f"No notebooks found under {NOTEBOOKS_DIR}")
        return

    for p in paths:
        nb = nbformat.read(p, as_version=4)
        nbformat.write(nb, p)
        print(f"  rewrote {p.name}")

    print(f"\nDone — {len(paths)} notebook(s) normalized.")


if __name__ == "__main__":
    main()
