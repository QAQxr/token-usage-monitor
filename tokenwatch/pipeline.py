"""Source-to-metrics helpers shared by CLI and dashboard."""

from __future__ import annotations

from pathlib import Path

from .metrics import MetricsStore, PriceTable
from .sources.jsonl import RolloutJsonlSource, newest_rollout


DEFAULT_SESSION_ROOT = Path("/home/o_o/.codex/sessions")


def load_store(path: str | Path, prices: PriceTable | None = None) -> MetricsStore:
    store = MetricsStore(prices=prices)
    store.apply_all(RolloutJsonlSource(path).events())
    return store


def load_newest_store(root: str | Path = DEFAULT_SESSION_ROOT, prices: PriceTable | None = None) -> tuple[Path | None, MetricsStore]:
    path = newest_rollout(root)
    return path, load_store(path, prices) if path else MetricsStore(prices=prices)
