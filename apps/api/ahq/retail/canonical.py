from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ahq.domain.retail import RetailSnapshot


def canonical_dump(snapshot: RetailSnapshot) -> dict[str, Any]:
    return snapshot.model_dump()


def canonical_hash(snapshot: RetailSnapshot) -> str:
    encoded = json.dumps(canonical_dump(snapshot), sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_snapshot(path: Path) -> RetailSnapshot:
    return RetailSnapshot.model_validate_json(path.read_bytes())
