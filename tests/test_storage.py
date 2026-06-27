"""Tests for the local-or-S3 storage layer (foodsafety.io.storage).

These run against ``LocalFileSystem`` in a tmp dir. Because S3 and local share the
same ``resolve`` / ``from_uri`` code path, exercising the local branch covers the
abstraction — the only S3-specific behaviour (region/credential resolution) lives in
pyarrow, not here.
"""

from __future__ import annotations

import joblib
import pandas as pd

from foodsafety.io import storage


def test_join_is_uri_safe_for_s3():
    # Path() would collapse the // after the scheme; join must not.
    assert storage.join("s3://bucket/raw", "a.parquet") == "s3://bucket/raw/a.parquet"
    assert storage.join("s3://bucket/raw/", "/a.parquet") == "s3://bucket/raw/a.parquet"
    assert storage.is_s3("s3://bucket/x")
    assert not storage.is_s3("/tmp/x")


def test_parquet_roundtrip_creates_parent(tmp_path):
    df = pd.DataFrame({"license_id": ["1", "2"], "risk_score": [0.1, 0.9]})
    # Nested dir does not exist yet — write must create it (LocalFileSystem won't).
    target = tmp_path / "processed" / "features" / "f.parquet"
    storage.write_parquet(df, target, index=False)
    assert storage.exists(target)
    pd.testing.assert_frame_equal(storage.read_parquet(target), df)


def test_text_roundtrip(tmp_path):
    target = tmp_path / "web-app-data" / "scores.json"
    storage.write_text('{"a":1}', target)
    assert storage.read_text(target) == '{"a":1}'


def test_bytes_roundtrip(tmp_path):
    target = tmp_path / "blob.bin"
    storage.write_bytes(b"\x00\x01\x02", target)
    assert storage.read_bytes(target) == b"\x00\x01\x02"


def test_joblib_roundtrip(tmp_path):
    obj = {"model": "logreg", "coef": [1.0, 2.0]}
    target = tmp_path / "models" / "m.joblib"
    storage.dump_joblib(obj, target)
    assert storage.load_joblib(target) == obj
    # Sanity: bytes are a real joblib object, loadable the normal way too.
    assert joblib.load(target) == obj


def test_exists_and_delete(tmp_path):
    target = tmp_path / "x.parquet"
    assert not storage.exists(target)
    storage.write_parquet(pd.DataFrame({"a": [1]}), target, index=False)
    assert storage.exists(target)
    storage.delete(target)
    assert not storage.exists(target)
    # Deleting a missing target is a no-op, not an error.
    storage.delete(target)


def test_glob_matches_pattern(tmp_path):
    shard_dir = tmp_path / "_shards"
    for i in range(3):
        storage.write_parquet(pd.DataFrame({"a": [i]}), shard_dir / f"page_{i:04d}.parquet")
    storage.write_text("ignore", shard_dir / "other.txt")
    hits = storage.glob(shard_dir, "page_*.parquet")
    assert [h.rsplit("/", 1)[1] for h in hits] == [
        "page_0000.parquet",
        "page_0001.parquet",
        "page_0002.parquet",
    ]
    # Returned targets feed straight back into read_parquet.
    assert storage.read_parquet(hits[1])["a"].tolist() == [1]


def test_glob_missing_dir_is_empty(tmp_path):
    assert storage.glob(tmp_path / "nope", "*.parquet") == []


def test_basename_local_and_s3():
    assert storage.basename("s3://bucket/models/baseline_sigmoid_abc.joblib") == (
        "baseline_sigmoid_abc.joblib"
    )
    assert storage.basename("/data/predictions/scores.parquet") == "scores.parquet"
    # Trailing slash is stripped before taking the final component.
    assert storage.basename("s3://bucket/web-app-data/") == "web-app-data"


def test_copy_is_byte_identical_and_creates_parent(tmp_path):
    # Larger-than-one-chunk payload exercises the streaming loop.
    src = tmp_path / "src" / "blob.bin"
    payload = bytes(range(256)) * 5000  # ~1.3 MB
    storage.write_bytes(payload, src)
    # Nested dst dir does not exist yet — copy must create it.
    dst = tmp_path / "dst" / "nested" / "blob.bin"
    storage.copy(src, dst)
    assert storage.exists(dst)
    assert storage.read_bytes(dst) == payload
