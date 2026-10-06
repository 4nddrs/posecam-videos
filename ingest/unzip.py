"""Extract video files and sidecars from a zip archive, safely."""
from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
SIDECAR_EXTENSIONS = {".txt", ".json"}


def _is_safe_member(name: str) -> bool:
    if not name or name.endswith("/"):
        return False
    pure = PurePosixPath(name)
    if pure.is_absolute():
        return False
    if ".." in pure.parts:
        return False
    return True


def _extract_by_suffixes(
    zip_path: Path, dest_dir: Path, suffixes: set[str]
) -> list[Path]:
    """Flatten every safe member whose lowercased suffix is in `suffixes`.

    Members are written to `dest_dir / Path(name).name`; absolute paths,
    `..` traversal and directory entries are skipped by `_is_safe_member`.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []

    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if not _is_safe_member(name):
                continue
            if Path(name).suffix.lower() not in suffixes:
                continue

            target = dest_dir / Path(name).name
            with zf.open(info) as source, open(target, "wb") as out:
                out.write(source.read())
            extracted.append(target)

    return extracted


def extract_videos(zip_path: Path, dest_dir: Path) -> list[Path]:
    """Extract video files from a zip, flattened into `dest_dir`."""
    return _extract_by_suffixes(zip_path, dest_dir, VIDEO_EXTENSIONS)


def extract_sidecars(
    zip_path: Path,
    dest_dir: Path,
    extensions: Iterable[str] = SIDECAR_EXTENSIONS,
) -> list[Path]:
    """Extract `.txt`/`.json` sidecars from a zip, flattened into `dest_dir`.

    `extensions` is matched case-insensitively against each member suffix.
    """
    return _extract_by_suffixes(zip_path, dest_dir, {ext.lower() for ext in extensions})
