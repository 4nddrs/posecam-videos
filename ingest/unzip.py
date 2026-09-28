"""Extract video files from a zip archive, safely."""
from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


def _is_safe_member(name: str) -> bool:
    if not name or name.endswith("/"):
        return False
    pure = PurePosixPath(name)
    if pure.is_absolute():
        return False
    if ".." in pure.parts:
        return False
    return True


def extract_videos(zip_path: Path, dest_dir: Path) -> list[Path]:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []

    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if not _is_safe_member(name):
                continue
            suffix = Path(name).suffix.lower()
            if suffix not in VIDEO_EXTENSIONS:
                continue

            target = dest_dir / Path(name).name
            with zf.open(info) as source, open(target, "wb") as out:
                out.write(source.read())
            extracted.append(target)

    return extracted
