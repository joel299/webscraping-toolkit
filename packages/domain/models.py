from dataclasses import dataclass, asdict
from enum import StrEnum
from typing import Any

class StopReason(StrEnum):
    TARGET_REACHED='target_reached'; SOURCE_EXHAUSTED='source_exhausted'; QUERIES_EXHAUSTED='queries_exhausted'; WORKER_ERROR='worker_error'; PARTIAL_RESULT='partial_result'

@dataclass(frozen=True)
class ScrapeRequest:
    requested_category: str
    city: str
    state: str
    max_leads: int = 5
    worker_count: int = 1
    reviews_mode: str = 'summary'
    dry_run: bool = True

@dataclass(frozen=True)
class JobEvent:
    job_id: str
    event_type: str
    place_identity: str | None
    payload: dict[str, Any]
    occurred_at: str

    def to_dict(self): return asdict(self)
