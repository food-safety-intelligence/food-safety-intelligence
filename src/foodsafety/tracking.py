"""Shared experiment-run provenance.

Every training run — notebooks and scripts alike — stamps the same Tier-0
block so ``reports/metrics/*.json`` and the model ``metadata.json`` sidecars are
comparable and reproducible across baseline / xgb / served runs:

  - ``git_commit`` + ``git_dirty`` — the exact code state
  - ``features_sha256`` — content hash of the features parquet (a stable dataset
    identity; the file's mtime changes on every rebuild even when content is
    identical, so it can't serve as one)
  - ``feature_set_version`` — short hash of the ordered feature contract
  - ``run_id`` — ``<date>_<short-sha>``; unique per commit so same-day reruns
    don't collide and overwrite each other's metrics

Build the block with ``provenance(...)`` and merge it into the metadata/report.
"""

from __future__ import annotations

import hashlib
import subprocess
from datetime import date
from pathlib import Path


def git_info(repo_root: Path) -> dict:
    """Current commit + dirty flag (best effort; ``None`` outside a git repo)."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=repo_root, text=True
            ).strip()
        )
        return {"commit": sha, "short": sha[:9], "dirty": dirty}
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"commit": None, "short": "nogit", "dirty": None}


def sha256_file(path: Path | str) -> str:
    """Content hash of a file/object — a stable dataset identity (mtime is not).

    Reads through the storage layer so it hashes a local path or an ``s3://`` URI
    identically. Lazy import keeps this module import-light for callers that only
    need ``git_info`` / ``feature_set_version``.
    """
    from foodsafety.io import storage

    return hashlib.sha256(storage.read_bytes(path)).hexdigest()


def feature_set_version(features: list[str]) -> str:
    """Short hash of the ordered feature contract — changes iff features do."""
    return hashlib.sha256("\n".join(features).encode()).hexdigest()[:12]


def provenance(features_path: Path, all_features: list[str], repo_root: Path) -> dict:
    """The Tier-0 provenance block shared by every training run."""
    git = git_info(repo_root)
    return {
        "run_id": f"{date.today().strftime('%Y%m%d')}_{git['short']}",
        "git_commit": git["commit"],
        "git_dirty": git["dirty"],
        "feature_set_version": feature_set_version(all_features),
        "features_sha256": sha256_file(features_path),
    }
