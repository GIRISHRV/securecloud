from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol


@dataclass(frozen=True)
class Record:
    id: int
    resource: str
    data: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "resource": self.resource, **self.data}


class RecordRepository(Protocol):
    def list(self, resource: str) -> list[Record]: ...
    def create(self, resource: str, data: dict[str, str]) -> Record: ...
    def update(self, resource: str, record_id: int, data: dict[str, str]) -> Record | None: ...
    def delete(self, resource: str, record_id: int) -> bool: ...
    def counts(self, resources: tuple[str, ...]) -> dict[str, int]: ...


class MemoryRecordRepository:
    def __init__(self) -> None:
        self._records: list[Record] = []
        self._next_id = 1
        self._lock = Lock()

    def list(self, resource: str) -> list[Record]:
        with self._lock:
            return [record for record in reversed(self._records) if record.resource == resource]

    def create(self, resource: str, data: dict[str, str]) -> Record:
        with self._lock:
            record = Record(self._next_id, resource, dict(data))
            self._records.append(record)
            self._next_id += 1
            return record

    def update(self, resource: str, record_id: int, data: dict[str, str]) -> Record | None:
        with self._lock:
            for index, record in enumerate(self._records):
                if record.resource == resource and record.id == record_id:
                    updated = Record(record.id, record.resource, dict(data))
                    self._records[index] = updated
                    return updated
        return None

    def delete(self, resource: str, record_id: int) -> bool:
        with self._lock:
            for index, record in enumerate(self._records):
                if record.resource == resource and record.id == record_id:
                    del self._records[index]
                    return True
        return False

    def counts(self, resources: tuple[str, ...]) -> dict[str, int]:
        with self._lock:
            return {
                resource: sum(record.resource == resource for record in self._records)
                for resource in resources
            }


class PostgresRecordRepository:
    """PostgreSQL persistence for allowlisted domain records."""

    def __init__(self, connection_string: str) -> None:
        try:
            import psycopg
            from psycopg.types.json import Jsonb
        except ImportError as exc:  # pragma: no cover - exercised by the container image
            raise RuntimeError("psycopg is required for PostgreSQL mode") from exc
        self._psycopg = psycopg
        self._jsonb = Jsonb
        self._connection_string = connection_string
        self._ensure_schema()

    def _connect(self):
        return self._psycopg.connect(self._connection_string, connect_timeout=5)

    def _ensure_schema(self) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS domain_records (
                    id BIGSERIAL PRIMARY KEY,
                    resource VARCHAR(32) NOT NULL,
                    data JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS domain_records_resource_id_idx ON domain_records(resource, id DESC)")

    def list(self, resource: str) -> list[Record]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, resource, data FROM domain_records WHERE resource = %s ORDER BY id DESC LIMIT 100",
                (resource,),
            )
            return [Record(row[0], row[1], row[2]) for row in cursor.fetchall()]

    def create(self, resource: str, data: dict[str, str]) -> Record:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO domain_records(resource, data)
                VALUES (%s, %s)
                RETURNING id, resource, data
                """,
                (resource, self._jsonb(data)),
            )
            row = cursor.fetchone()
            return Record(row[0], row[1], row[2])

    def update(self, resource: str, record_id: int, data: dict[str, str]) -> Record | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE domain_records SET data = %s, updated_at = NOW() WHERE resource = %s AND id = %s RETURNING id, resource, data",
                (self._jsonb(data), resource, record_id),
            )
            row = cursor.fetchone()
            return Record(row[0], row[1], row[2]) if row else None

    def delete(self, resource: str, record_id: int) -> bool:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM domain_records WHERE resource = %s AND id = %s", (resource, record_id))
            return cursor.rowcount == 1

    def counts(self, resources: tuple[str, ...]) -> dict[str, int]:
        counts = {resource: 0 for resource in resources}
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT resource, COUNT(*) FROM domain_records WHERE resource = ANY(%s) GROUP BY resource",
                (list(resources),),
            )
            for resource, count in cursor.fetchall():
                counts[resource] = count
        return counts
