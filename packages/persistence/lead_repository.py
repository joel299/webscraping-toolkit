from dataclasses import dataclass
from typing import Any, Callable

COMMERCIAL = ("lead_status", "pipeline_stage", "responded", "converted")

@dataclass(frozen=True)
class PersistenceResult:
    action: str
    verified: bool
    row: dict[str, Any] | None

class LeadRepository:
    """Idempotent V2 writer that never regresses V1 commercial fields."""
    def __init__(self, get: Callable, insert: Callable, update: Callable):
        self.get = get
        self.insert = insert
        self.update = update

    def upsert(self, identity: str, discovery: dict[str, Any]) -> PersistenceResult:
        existing = self.get(identity)
        if existing:
            payload = {k: v for k, v in discovery.items() if k not in COMMERCIAL and v not in (None, "", [])}
            self.update(identity, payload)
            action = "updated"
        else:
            payload = dict(discovery)
            self.insert(payload)
            action = "inserted"
        fresh = self.get(identity)
        if not fresh:
            return PersistenceResult("failed", False, None)
        required = ("id", "place_name", "source_category", "source_city", "source_state")
        verified = all(k in fresh for k in required)
        return PersistenceResult(action, verified, fresh)
