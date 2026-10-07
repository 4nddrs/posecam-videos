"""Cloudflare R2 adapter implementing the VideoPublisher port.

R2 exposes an S3-compatible API, so this adapter is a thin wrapper
around a duck-typed boto3 S3 client. The client is always injected by
the caller (never constructed inside the class) so tests can use a
fake client with no boto3 dependency. The module-level
`build_r2_publisher` factory is the only place that lazily imports
boto3 and wires a real client.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ingest.ports import PublishedVideo

_DEFAULT_CONTENT_TYPE = "application/octet-stream"
_MANIFEST_KEY = "manifest.json"

# Same content types the sidecar backfill uses (ingest.sidecars._CONTENT_TYPES).
_SIDECAR_CONTENT_TYPES = {
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
}


class R2VideoPublisher:
    """VideoPublisher adapter backed by a Cloudflare R2 S3-compatible bucket."""

    def __init__(self, client: Any, bucket: str, public_base_url: str) -> None:
        self._client = client
        self._bucket = bucket
        self._public_base_url = public_base_url.rstrip("/")

    def publish(
        self, video_path: Path, day: str, poster_path: Path | None = None
    ) -> PublishedVideo:
        video_path = Path(video_path)
        key = f"{day}/{video_path.name}"
        content_type, _ = mimetypes.guess_type(video_path.name)
        if content_type is None:
            content_type = _DEFAULT_CONTENT_TYPE

        self._client.upload_file(
            str(video_path),
            self._bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

        poster_url = None
        if poster_path is not None:
            poster_key = f"{day}/{video_path.stem}.jpg"
            self._client.upload_file(
                str(poster_path),
                self._bucket,
                poster_key,
                ExtraArgs={"ContentType": "image/jpeg"},
            )
            poster_url = f"{self._public_base_url}/{quote(poster_key)}"

        return PublishedVideo(
            id=key,
            name=video_path.name,
            url=f"{self._public_base_url}/{quote(key)}",
            poster_url=poster_url,
        )

    def publish_sidecar(self, sidecar_path: Path, day: str, session: str) -> str:
        sidecar_path = Path(sidecar_path)
        key = f"{day}/{session}/{sidecar_path.name}"
        content_type = _SIDECAR_CONTENT_TYPES.get(
            sidecar_path.suffix.lower(), _DEFAULT_CONTENT_TYPE
        )
        self._client.upload_file(
            str(sidecar_path),
            self._bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return f"{self._public_base_url}/{quote(key)}"

    def publish_manifest(self, manifest_path: Path) -> str:
        key = _MANIFEST_KEY
        self._client.upload_file(
            str(manifest_path),
            self._bucket,
            key,
            ExtraArgs={"ContentType": "application/json", "CacheControl": "no-cache"},
        )
        return f"{self._public_base_url}/{key}"


def build_r2_publisher(
    account_id: str,
    access_key_id: str,
    secret_access_key: str,
    bucket: str,
    public_base_url: str,
    endpoint_url: str | None = None,
) -> R2VideoPublisher:
    """Build an R2VideoPublisher backed by a real boto3 S3 client.

    Imports boto3 lazily so callers that only need the protocol/tests
    do not require it installed.
    """
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url or f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )
    return R2VideoPublisher(client, bucket=bucket, public_base_url=public_base_url)
