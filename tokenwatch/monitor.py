"""Refreshable, UI-independent monitoring state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Callable, Literal

from .metrics import MetricsStore
from .pipeline import DEFAULT_SESSION_ROOT, load_newest_store


MonitorStatus = Literal["active", "idle", "no_data", "no_session", "error"]
StoreLoader = Callable[[Path], tuple[Path | None, MetricsStore]]


@dataclass(frozen=True)
class MonitorState:
    """The complete result of one safe refresh attempt."""

    status: MonitorStatus
    message: str
    source_file: Path | None = None
    source_modified_at: datetime | None = None
    snapshot: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    refreshed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SnapshotRefresher:
    """Load the newest rollout without coupling a UI to the data source."""

    def __init__(
        self,
        root: str | Path = DEFAULT_SESSION_ROOT,
        loader: StoreLoader = load_newest_store,
        active_window_seconds: float = 120.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.root = Path(root)
        self.loader = loader
        self.active_window_seconds = max(float(active_window_seconds), 0.0)
        self.clock = clock

    def refresh(self) -> MonitorState:
        refreshed_at = datetime.now(timezone.utc)
        try:
            source_file, store = self.loader(self.root)
            snapshot = store.snapshot()
        except Exception as exc:  # UI refresh must never take down the app.
            return MonitorState(
                status="error",
                message="Read error · rollout data could not be parsed",
                error=f"{type(exc).__name__}: {exc}",
                refreshed_at=refreshed_at,
            )

        if source_file is None:
            return MonitorState(
                status="no_data",
                message="No Codex rollout found",
                snapshot=snapshot,
                refreshed_at=refreshed_at,
            )

        source_modified_at = self._modified_at(source_file)
        sessions = snapshot.get("sessions") or []
        if not sessions:
            return MonitorState(
                status="no_session",
                message="No active Codex session",
                source_file=source_file,
                source_modified_at=source_modified_at,
                snapshot=snapshot,
                refreshed_at=refreshed_at,
            )

        is_active = self._is_recent(source_file)
        return MonitorState(
            status="active" if is_active else "idle",
            message="Live · local read-only" if is_active else "Idle · no active session",
            source_file=source_file,
            source_modified_at=source_modified_at,
            snapshot=snapshot,
            refreshed_at=refreshed_at,
        )

    def _modified_at(self, path: Path) -> datetime | None:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return None

    def _is_recent(self, path: Path) -> bool:
        try:
            age = max(0.0, self.clock() - path.stat().st_mtime)
        except OSError:
            return False
        return age <= self.active_window_seconds


def latest_scope(snapshot: dict[str, Any], scope: Literal["session", "turn"]) -> dict[str, Any] | None:
    """Select the newest Session or Turn for presentation."""

    values = snapshot.get("sessions" if scope == "session" else "turns") or []
    return values[-1] if values else None
