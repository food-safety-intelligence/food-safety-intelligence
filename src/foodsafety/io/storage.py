"""Local-or-S3 storage layer for every pipeline IO site.

The pipeline reads/writes parquet, JSON, and joblib artifacts under a single base
location chosen by ``FOODSAFETY_DATA_DIR`` (see ``config``). That base is either a
local path (laptop / CI default) or an ``s3://…`` URI (Phase-2 AWS). Routing all IO
through this module means one code path serves both: ``resolve`` turns any target
into a ``(pyarrow.fs.FileSystem, path)`` pair, so the same functions write to disk in
tests and to S3 in production.

No new dependencies: ``pyarrow`` (already pinned) provides ``S3FileSystem`` /
``LocalFileSystem``, and ``joblib`` (already pinned) serialises models to bytes we put
as objects. S3 credentials + region come from the standard AWS chain
(``~/.aws/credentials``, env vars, or an instance/role) that ``pyarrow`` and ``boto3``
both read — nothing AWS-specific is hard-coded here.
"""

from __future__ import annotations

import fnmatch
import io
import os

import joblib
import pandas as pd
from pyarrow.fs import (
    FileSelector,
    FileSystem,
    FileType,
    LocalFileSystem,
)

# Target = anything stringifiable to a path or an s3:// URI.
Target = str | os.PathLike


def is_s3(target: Target) -> bool:
    """True if ``target`` is an ``s3://`` URI rather than a local path."""
    return str(target).startswith("s3://")


def resolve(target: Target) -> tuple[FileSystem, str]:
    """Return the ``(filesystem, path)`` pair for a local path or s3:// URI.

    For S3 we defer to pyarrow's URI parser (which also resolves the bucket region
    and reads the default AWS credential chain). For local targets we normalise to
    an absolute path and use ``LocalFileSystem`` directly — more robust than
    ``from_uri`` for relative paths, ``~`` expansion, and Path inputs.
    """
    s = str(target)
    if is_s3(s):
        filesystem, path = FileSystem.from_uri(s)
        return filesystem, path
    return LocalFileSystem(), os.path.abspath(os.path.expanduser(s))


def join(base: Target, *parts: str) -> str:
    """URI-safe join. Never use ``Path /`` on an ``s3://`` URI — it collapses the
    double slash after the scheme (``s3:/bucket``)."""
    out = str(base).rstrip("/")
    for part in parts:
        out = f"{out}/{str(part).strip('/')}"
    return out


def _ensure_parent(filesystem: FileSystem, path: str) -> None:
    """Create the parent directory for a local write.

    ``LocalFileSystem`` does not auto-create parent dirs on ``open_output_stream`` /
    ``to_parquet``, so we make them here. S3 has no real directories (keys are flat),
    so this is a no-op there.
    """
    if isinstance(filesystem, LocalFileSystem):
        parent = path.rsplit("/", 1)[0]
        if parent:
            filesystem.create_dir(parent, recursive=True)


def exists(target: Target) -> bool:
    """True if an object/file exists at ``target``."""
    filesystem, path = resolve(target)
    return filesystem.get_file_info(path).type != FileType.NotFound


def delete(target: Target) -> None:
    """Delete the object/file if present (no error if already gone)."""
    filesystem, path = resolve(target)
    if filesystem.get_file_info(path).type != FileType.NotFound:
        filesystem.delete_file(path)


def glob(directory: Target, pattern: str) -> list[str]:
    """List files directly under ``directory`` whose base name matches ``pattern``.

    Returns full targets in the same scheme as the input (so the results can be fed
    straight back into ``resolve`` / ``read_parquet``). Replaces ``Path.glob`` for the
    keyset shard dir, which on S3 has no directory object to walk.
    """
    filesystem, path = resolve(directory)
    selector = FileSelector(path, allow_not_found=True, recursive=False)
    base = str(directory).rstrip("/")
    return sorted(
        f"{base}/{info.base_name}"
        for info in filesystem.get_file_info(selector)
        if info.type == FileType.File and fnmatch.fnmatch(info.base_name, pattern)
    )


def read_parquet(target: Target, **kwargs) -> pd.DataFrame:
    """Read a parquet file/object into a DataFrame."""
    filesystem, path = resolve(target)
    return pd.read_parquet(path, filesystem=filesystem, **kwargs)


def write_parquet(df: pd.DataFrame, target: Target, **kwargs) -> None:
    """Write a DataFrame to parquet at ``target`` (creating local parents)."""
    filesystem, path = resolve(target)
    _ensure_parent(filesystem, path)
    df.to_parquet(path, filesystem=filesystem, **kwargs)


def read_bytes(target: Target) -> bytes:
    """Read raw bytes from a file/object."""
    filesystem, path = resolve(target)
    with filesystem.open_input_stream(path) as f:
        return f.read()


def write_bytes(data: bytes, target: Target) -> None:
    """Write raw bytes to a file/object (creating local parents)."""
    filesystem, path = resolve(target)
    _ensure_parent(filesystem, path)
    with filesystem.open_output_stream(path) as f:
        f.write(data)


def read_text(target: Target, encoding: str = "utf-8") -> str:
    """Read UTF-8 text (e.g. a JSON document)."""
    return read_bytes(target).decode(encoding)


def write_text(text: str, target: Target, encoding: str = "utf-8") -> None:
    """Write UTF-8 text (e.g. a JSON document)."""
    write_bytes(text.encode(encoding), target)


def dump_joblib(obj: object, target: Target) -> None:
    """Serialise a model with joblib and write it as a single object/file.

    joblib writes to a path, not a filesystem handle, so we go through an in-memory
    buffer and hand the bytes to ``write_bytes`` — same code path for local and S3.
    """
    buffer = io.BytesIO()
    joblib.dump(obj, buffer)
    write_bytes(buffer.getvalue(), target)


def load_joblib(target: Target) -> object:
    """Load a joblib-serialised object from a file/object."""
    return joblib.load(io.BytesIO(read_bytes(target)))
