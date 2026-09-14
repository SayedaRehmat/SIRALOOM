from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.infrastructure.db.models import AnalysisPartition, now


@dataclass(frozen=True)
class ResourceProfile:
    name: str
    cpu: float
    memory_mb: int


PROFILES = {
    "LIGHT": ResourceProfile("LIGHT", 0.5, 512),
    "STANDARD": ResourceProfile("STANDARD", 1.0, 1024),
    "HEAVY": ResourceProfile("HEAVY", 2.0, 4096),
}


class PartitionCapacityError(RuntimeError):
    pass


class PartitionLeaseError(RuntimeError):
    pass


def profile_for(name: str) -> ResourceProfile:
    try:
        return PROFILES[str(name).upper()]
    except KeyError as exc:
        raise ValueError(f"Unknown partition resource class: {name}") from exc


def configure_partition(partition: AnalysisPartition, profile: str = "STANDARD") -> None:
    p = profile_for(profile)
    partition.resource_class = p.name
    partition.cpu_request = p.cpu
    partition.memory_mb = p.memory_mb


class PartitionScheduler:
    """DB-backed resource-aware lease scheduler.

    Leases make work restartable across worker processes. Capacity is calculated
    from active, unexpired leases, so concurrent workers cannot exceed the
    configured CPU/RAM envelope when they use this scheduler contract.
    """

    def __init__(self, db: Session, *, cpu_capacity: float | None = None, memory_mb: int | None = None, lease_seconds: int | None = None):
        self.db = db
        self.cpu_capacity = float(cpu_capacity if cpu_capacity is not None else settings.partition_scheduler_cpu_capacity)
        self.memory_capacity = int(memory_mb if memory_mb is not None else settings.partition_scheduler_memory_mb)
        self.lease_seconds = int(lease_seconds if lease_seconds is not None else settings.partition_lease_seconds)

    def _requeue_expired(self, analysis_id: UUID, step_id: str) -> int:
        t = now()
        result = self.db.execute(
            update(AnalysisPartition)
            .where(
                AnalysisPartition.analysis_id == analysis_id,
                AnalysisPartition.step_id == step_id,
                AnalysisPartition.status == "RUNNING",
                AnalysisPartition.lease_expires_at.is_not(None),
                AnalysisPartition.lease_expires_at < t,
            )
            .values(status="READY", lease_owner=None, lease_expires_at=None)
        )
        self.db.commit()
        return int(result.rowcount or 0)

    def capacity(self) -> dict[str, float | int]:
        t = now()
        rows = self.db.execute(
            select(func.coalesce(func.sum(AnalysisPartition.cpu_request), 0.0), func.coalesce(func.sum(AnalysisPartition.memory_mb), 0))
            .where(AnalysisPartition.status == "RUNNING", AnalysisPartition.lease_expires_at > t)
        ).one()
        return {"cpu_used": float(rows[0] or 0), "memory_mb_used": int(rows[1] or 0), "cpu_capacity": self.cpu_capacity, "memory_mb_capacity": self.memory_capacity}

    def claim_next(self, analysis_id: UUID, step_id: str, worker_id: str) -> AnalysisPartition | None:
        self._requeue_expired(analysis_id, step_id)
        candidates = self.db.scalars(
            select(AnalysisPartition)
            .where(AnalysisPartition.analysis_id == analysis_id, AnalysisPartition.step_id == step_id, AnalysisPartition.status == "READY")
            .order_by(AnalysisPartition.ordinal)
        ).all()
        active = self.capacity()
        for part in candidates:
            if part.attempt >= settings.partition_max_attempts:
                part.status = "FAILED"
                part.error_code = "MAX_ATTEMPTS_EXCEEDED"
                self.db.commit()
                continue
            if active["cpu_used"] + float(part.cpu_request) > self.cpu_capacity:
                continue
            if active["memory_mb_used"] + int(part.memory_mb) > self.memory_capacity:
                continue
            t = now()
            part.status = "RUNNING"
            part.attempt += 1
            part.lease_owner = worker_id
            part.lease_expires_at = t + timedelta(seconds=self.lease_seconds)
            part.started_at = part.started_at or t
            part.updated_at = t
            self.db.commit()
            return part
        return None

    def heartbeat(self, partition_id: UUID, worker_id: str) -> AnalysisPartition:
        part = self.db.get(AnalysisPartition, partition_id)
        if not part or part.status != "RUNNING" or part.lease_owner != worker_id:
            raise PartitionLeaseError("Partition lease is not owned by this worker")
        part.lease_expires_at = now() + timedelta(seconds=self.lease_seconds)
        part.updated_at = now()
        self.db.commit()
        return part

    def succeed(self, partition_id: UUID, worker_id: str, *, metadata: dict | None = None) -> AnalysisPartition:
        part = self._owned(partition_id, worker_id)
        part.status = "SUCCEEDED"
        part.lease_owner = None
        part.lease_expires_at = None
        part.completed_at = now()
        if metadata:
            part.metadata_json = {**(part.metadata_json or {}), **metadata}
        part.updated_at = now()
        self.db.commit()
        return part

    def fail(self, partition_id: UUID, worker_id: str, *, error_code: str, error_message: str) -> AnalysisPartition:
        part = self._owned(partition_id, worker_id)
        part.error_code = error_code
        part.error_message = error_message
        part.lease_owner = None
        part.lease_expires_at = None
        part.status = "READY" if part.attempt < settings.partition_max_attempts else "FAILED"
        part.updated_at = now()
        self.db.commit()
        return part

    def _owned(self, partition_id: UUID, worker_id: str) -> AnalysisPartition:
        part = self.db.get(AnalysisPartition, partition_id)
        if not part or part.status != "RUNNING" or part.lease_owner != worker_id:
            raise PartitionLeaseError("Partition lease is not owned by this worker")
        return part
