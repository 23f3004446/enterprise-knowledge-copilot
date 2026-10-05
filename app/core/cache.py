from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class CacheEntry:
    role: str
    permission_scope: str
    model: str
    query_vector: np.ndarray
    value: Any
    expires_at: float


class SemanticAnswerCache:
    def __init__(self, ttl_seconds: int = 300, similarity_threshold: float = 0.96) -> None:
        self.ttl_seconds = ttl_seconds
        self.similarity_threshold = similarity_threshold
        self._entries: list[CacheEntry] = []
        self._lock = threading.Lock()

    @staticmethod
    def scope_key(access_levels: set[str]) -> str:
        return hashlib.sha256(",".join(sorted(access_levels)).encode()).hexdigest()

    def get(self, query_vector: np.ndarray, role: str, scope: str, model: str) -> Any | None:
        now = time.monotonic()
        vector = np.asarray(query_vector, dtype="float32").reshape(-1)
        with self._lock:
            self._entries = [entry for entry in self._entries if entry.expires_at > now]
            for entry in reversed(self._entries):
                if entry.role != role or entry.permission_scope != scope or entry.model != model:
                    continue
                score = float(np.dot(vector, entry.query_vector))
                if score >= self.similarity_threshold:
                    return entry.value
        return None

    def set(self, query_vector: np.ndarray, role: str, scope: str, model: str, value: Any) -> None:
        vector = np.asarray(query_vector, dtype="float32").reshape(-1).copy()
        with self._lock:
            self._entries.append(
                CacheEntry(role, scope, model, vector, value, time.monotonic() + self.ttl_seconds)
            )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
