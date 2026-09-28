"""JSON-backed idempotency state store."""
from __future__ import annotations

import json
from pathlib import Path


class JsonStateStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def processed_ids(self) -> set[str]:
        if not self._path.exists():
            return set()
        data = json.loads(self._path.read_text())
        return set(data.get("processed", []))

    def mark_processed(self, zip_id: str) -> None:
        processed = self.processed_ids()
        processed.add(zip_id)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"processed": sorted(processed)}, indent=2))
