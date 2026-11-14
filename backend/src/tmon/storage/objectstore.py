"""Raw payload storage (MinIO / S3). A payload is stored before it is parsed."""

from __future__ import annotations

import hashlib
import io
import os
from datetime import datetime
from pathlib import Path
from typing import Protocol

from minio import Minio
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.core.config import get_settings
from tmon.storage.models import RawPayload


class ObjectStore(Protocol):
    def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, bucket: str, key: str) -> bytes: ...
    def version(self, bucket: str, key: str) -> str:
        """A token that changes whenever the object is rewritten (raises if it does not exist)."""
        ...


class MinioStore:
    def __init__(self, client: Minio | None = None) -> None:
        s = get_settings()
        self._client = client or Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=s.minio_secure,
        )
        self._known: set[str] = set()

    def _ensure(self, bucket: str) -> None:
        if bucket not in self._known:
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)
            self._known.add(bucket)

    def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self._ensure(bucket)
        self._client.put_object(bucket, key, io.BytesIO(data), len(data), content_type=content_type)

    def get(self, bucket: str, key: str) -> bytes:
        resp = self._client.get_object(bucket, key)
        try:
            return bytes(resp.read())
        finally:
            resp.close()
            resp.release_conn()

    def version(self, bucket: str, key: str) -> str:
        st = self._client.stat_object(bucket, key)
        return f"{st.etag}-{st.last_modified}"


class MemoryStore:
    """In-memory store for tests and offline runs."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.objects[(bucket, key)] = data

    def get(self, bucket: str, key: str) -> bytes:
        return self.objects[(bucket, key)]

    def version(self, bucket: str, key: str) -> str:
        return hashlib.sha256(self.objects[(bucket, key)]).hexdigest()


class FileStore:
    """Filesystem store for runs without Docker. Same layout as the S3 buckets: root/bucket/key."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def _path(self, bucket: str, key: str) -> Path:
        p = (self._root / bucket / key).resolve()
        if self._root.resolve() not in p.parents:
            raise ValueError(f"key escapes the store: {key}")
        return p

    def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        p = self._path(bucket, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        # write beside, then swap: readers never see a half-written file, and every rewrite is a
        # new file, so ``version`` changes even for a same-size rewrite within one clock tick
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)

    def get(self, bucket: str, key: str) -> bytes:
        return self._path(bucket, key).read_bytes()

    def version(self, bucket: str, key: str) -> str:
        st = self._path(bucket, key).stat()
        return f"{st.st_ino}-{st.st_mtime_ns}-{st.st_size}"


def get_object_store() -> ObjectStore:
    """The store selected by ``TMON_OBJECT_STORE`` (``minio`` or ``file``)."""
    s = get_settings()
    if s.object_store == "file":
        return FileStore(s.object_store_dir)
    return MinioStore()


def raw_key(source: str, fetched_at: datetime, sha256: str, ext: str) -> str:
    return f"{source}/{fetched_at:%Y/%m/%d}/{fetched_at:%H%M%S}-{sha256[:16]}.{ext}"


def store_raw_payload(
    session: Session,
    store: ObjectStore,
    *,
    source: str,
    source_url: str,
    payload: bytes,
    fetched_at: datetime,
    ext: str = "txt",
    content_type: str = "text/plain",
) -> RawPayload:
    """Persist ``payload`` in object storage and index it. Must precede parsing."""
    digest = hashlib.sha256(payload).hexdigest()
    key = raw_key(source, fetched_at, digest, ext)
    existing = session.scalar(select(RawPayload).where(RawPayload.object_key == key))
    if existing is not None:  # identical payload re-fetched within the same second
        return existing
    store.put(get_settings().minio_raw_bucket, key, payload, content_type)
    row = RawPayload(
        source=source,
        source_url=source_url,
        object_key=key,
        sha256=digest,
        size_bytes=len(payload),
        fetched_at=fetched_at,
    )
    session.add(row)
    session.flush()
    return row
