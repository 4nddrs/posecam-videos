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
    zip_path: Path,
    dest_dir: Path,
    suffixes: set[str],
    preserve_dirs: bool = False,
) -> list[Path]:
    """Extract every safe member whose lowercased suffix is in `suffixes`.

    By default members are flattened to `dest_dir / Path(name).name`. When
    `preserve_dirs` is true the archive's relative directory structure is kept,
    writing each member to `dest_dir / PurePosixPath(name)`. Absolute paths,
    `..` traversal and directory entries are skipped by `_is_safe_member` in
    either mode.
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

            if preserve_dirs:
                target = dest_dir / PurePosixPath(name)
                target.parent.mkdir(parents=True, exist_ok=True)
            else:
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
    preserve_dirs: bool = False,
) -> list[Path]:
    """Extract `.txt`/`.json` sidecars from a zip.

    `extensions` is matched case-insensitively against each member suffix.
    Members are flattened into `dest_dir` unless `preserve_dirs` is true, in
    which case their relative directories are preserved.
    """
    return _extract_by_suffixes(
        zip_path, dest_dir, {ext.lower() for ext in extensions}, preserve_dirs
    )
