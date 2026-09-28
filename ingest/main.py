"""CLI entry point: wires the Drive source, R2 publisher and JSON state
store, then runs the ingest use case once.

Usage: python -m ingest.main

Reads configuration from environment variables, optionally preloaded
from a `.env` file at the repository root (existing environment
variables always take precedence).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, MutableMapping

from ingest.adapters.drive import (
    DriveZipSource,
    build_drive_source,
    build_drive_source_with_api_key,
)
from ingest.adapters.ffmpeg import build_processor
from ingest.adapters.r2 import R2VideoPublisher, build_r2_publisher
from ingest.ports import VideoPublisher, ZipSource
from ingest.state import JsonStateStore
from ingest.use_case import IngestReport, run_ingest

_REQUIRED_VARS = (
    "DRIVE_FOLDER_ID",
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_PUBLIC_BASE_URL",
)

_DEFAULT_MANIFEST_PATH = "site/manifest.json"
_DEFAULT_STATE_PATH = "ingest/state.json"


@dataclass(frozen=True)
class Config:
    drive_folder_id: str
    google_api_key: str | None
    google_service_account_file: Path | None
    r2_account_id: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket: str
    r2_public_base_url: str
    r2_endpoint: str | None
    manifest_path: Path
    state_path: Path
    workdir: Path
    max_zips_per_run: int = 10


def load_config(env: Mapping[str, str]) -> Config:
    """Build a Config from an environment mapping.

    Raises ValueError listing every missing required variable name.
    """
    missing = [name for name in _REQUIRED_VARS if not env.get(name)]
    api_key = env.get("GOOGLE_API_KEY") or None
    sa_file = env.get("GOOGLE_SERVICE_ACCOUNT_FILE") or None
    if not api_key and not sa_file:
        missing.insert(1, "GOOGLE_API_KEY")
    bucket = env.get("R2_BUCKET_NAME") or env.get("R2_BUCKET")
    if not bucket:
        missing.append("R2_BUCKET_NAME")
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    workdir = env.get("WORKDIR")
    return Config(
        drive_folder_id=env["DRIVE_FOLDER_ID"],
        google_api_key=api_key,
        google_service_account_file=Path(sa_file) if sa_file else None,
        r2_account_id=env["R2_ACCOUNT_ID"],
        r2_access_key_id=env["R2_ACCESS_KEY_ID"],
        r2_secret_access_key=env["R2_SECRET_ACCESS_KEY"],
        r2_bucket=bucket,
        r2_public_base_url=env["R2_PUBLIC_BASE_URL"],
        r2_endpoint=env.get("R2_ENDPOINT") or None,
        manifest_path=Path(env.get("MANIFEST_PATH", _DEFAULT_MANIFEST_PATH)),
        state_path=Path(env.get("STATE_PATH", _DEFAULT_STATE_PATH)),
        workdir=Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="ingest-")),
        max_zips_per_run=int(env.get("MAX_ZIPS_PER_RUN") or 10),
    )


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse `.env` file contents into a dict.

    Supports `KEY=VALUE` lines, blank lines and `#` comments. Values
    are stripped of surrounding whitespace.
    """
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def apply_dotenv(text: str, env: MutableMapping[str, str]) -> None:
    """Apply parsed `.env` contents into env, never overriding existing keys."""
    for key, value in parse_dotenv(text).items():
        if key not in env:
            env[key] = value


def load_dotenv_file(path: Path, env: MutableMapping[str, str]) -> None:
    path = Path(path)
    if path.exists():
        apply_dotenv(path.read_text(), env)


def _default_source_builder(cfg: Config) -> ZipSource:
    if cfg.google_api_key:
        return build_drive_source_with_api_key(cfg.drive_folder_id, cfg.google_api_key)
    assert cfg.google_service_account_file is not None
    return build_drive_source(cfg.drive_folder_id, cfg.google_service_account_file)


DEFAULT_SOURCE_BUILDER: Callable[[Config], ZipSource] = _default_source_builder
DEFAULT_PUBLISHER_BUILDER: Callable[[Config], VideoPublisher] = lambda cfg: build_r2_publisher(
    cfg.r2_account_id,
    cfg.r2_access_key_id,
    cfg.r2_secret_access_key,
    cfg.r2_bucket,
    cfg.r2_public_base_url,
    endpoint_url=cfg.r2_endpoint,
)


def run(
    config: Config,
    source_builder: Callable[[Config], ZipSource] = DEFAULT_SOURCE_BUILDER,
    publisher_builder: Callable[[Config], VideoPublisher] = DEFAULT_PUBLISHER_BUILDER,
) -> IngestReport:
    source = source_builder(config)
    publisher = publisher_builder(config)
    state = JsonStateStore(config.state_path)

    return run_ingest(
        source=source,
        publisher=publisher,
        state=state,
        manifest_path=config.manifest_path,
        workdir=config.workdir,
        max_zips=config.max_zips_per_run,
        processor=build_processor(),
    )


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv_file(repo_root / ".env", os.environ)

    try:
        config = load_config(os.environ)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    report = run(config)
    print(
        json.dumps(
            {
                "processed": report.processed,
                "skipped": report.skipped,
                "failed": report.failed,
                "deferred": report.deferred,
            }
        )
    )

    if report.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
