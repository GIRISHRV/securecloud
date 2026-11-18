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
    ):
        if max_line_bytes <= 0 or max_records <= 0:
            raise ValueError("collector limits must be positive")
        self.path = path
        self.identities = identities
        self.max_line_bytes = max_line_bytes
        self.max_records = max_records
        self.offset = 0
        self._file_identity: tuple[int, int] | None = None

    def poll(self) -> CollectionBatch:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return CollectionBatch((), 0, self.offset)

        identity = (stat.st_dev, stat.st_ino)
        if self._file_identity not in {None, identity} or stat.st_size < self.offset:
            self.offset = 0
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
                    flows.append(
                        normalize_hubble_json_line(
                            text,
                            index,
                            max_bytes=self.max_line_bytes,
                        ),
                    )
                except (UnicodeDecodeError, HubbleNormalizationError):
                    rejected += 1
        return CollectionBatch(tuple(flows), rejected, self.offset)
