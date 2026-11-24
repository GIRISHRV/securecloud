"""Bounded incremental reader for Hubble's rotating JSON flow-export file."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .hubble import (
    HubbleNormalizationError,
    IdentityIndex,
    normalize_hubble_json_line,
)
from .schema import NormalizedFlow


@dataclass(frozen=True)
class CollectionBatch:
    flows: tuple[NormalizedFlow, ...]
    rejected_count: int
    next_offset: int


class HubbleJsonFileCollector:
    """Read complete new lines only and recover safely when the exporter rotates."""

    def __init__(
        self,
        path: Path,
        identities: Callable[[], IdentityIndex],
        *,
        max_line_bytes: int = 1_048_576,
        max_records: int = 10_000,
        resume_window_bytes: int | None = 4 * 1_048_576,
    ):
        if max_line_bytes <= 0 or max_records <= 0:
            raise ValueError("collector limits must be positive")
        self.path = path
        self.identities = identities
        self.max_line_bytes = max_line_bytes
        self.max_records = max_records
        self.offset = 0
        self._file_identity: tuple[int, int] | None = None
        # On first start, skip an old capture backlog and resume near the end.
        # Ingestion is idempotent by event ID, so earlier flows were already
        # stored by a previous run; None replays the whole file.
        self.resume_window_bytes = resume_window_bytes

    def poll(self) -> CollectionBatch:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return CollectionBatch((), 0, self.offset)

        identity = (stat.st_dev, stat.st_ino)
        if self._file_identity not in {None, identity} or stat.st_size < self.offset:
            self.offset = 0
        if (
            self._file_identity is None
            and self.resume_window_bytes is not None
            and stat.st_size > self.resume_window_bytes
        ):
            with self.path.open("rb") as stream:
                stream.seek(stat.st_size - self.resume_window_bytes)
                stream.readline()  # drop the partial line we landed in
                self.offset = stream.tell()
        self._file_identity = identity
        index = self.identities()
        flows: list[NormalizedFlow] = []
        rejected = 0

        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            records = 0
            while records < self.max_records:
                line_start = stream.tell()
                raw = stream.readline(self.max_line_bytes + 2)
                if not raw:
                    break
                if len(raw) > self.max_line_bytes:
                    while raw and not raw.endswith(b"\n"):
                        raw = stream.readline(self.max_line_bytes + 2)
                    self.offset = stream.tell()
                    rejected += 1
                    records += 1
                    continue
                if not raw.endswith(b"\n"):
                    stream.seek(line_start)
                    break
                self.offset = stream.tell()
                records += 1
                try:
                    text = raw.decode("utf-8").rstrip("\r\n")
                    flow = normalize_hubble_json_line(
                        text,
                        index,
                        max_bytes=self.max_line_bytes,
                    )
                    # A forwarded reply leg would look like a reverse graph edge that
                    # no workload opened; drops are always kept as evidence.
                    if flow.is_reply and flow.verdict == "forwarded":
                        continue
                    flows.append(flow)
                except (UnicodeDecodeError, HubbleNormalizationError):
                    rejected += 1
        return CollectionBatch(tuple(flows), rejected, self.offset)
