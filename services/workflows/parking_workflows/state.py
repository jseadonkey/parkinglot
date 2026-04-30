from __future__ import annotations

from enum import StrEnum


class WorkflowStep(StrEnum):
    ingest = "ingest"
    score = "score"
    enrich = "enrich"
    memo = "memo"
    contract_draft = "contract_draft"
    awaiting_human = "awaiting_human"


class WorkflowStatus(StrEnum):
    pending = "pending"
    running = "running"
    blocked = "blocked"
    completed = "completed"
    failed = "failed"
