from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

RESERVE_SECONDS = 30 * 86400
HISTORY = 50


@dataclass
class State:
    path: Path
    numbers: dict[str, dict] = field(default_factory=dict)
    health: dict[str, list] = field(default_factory=dict)
    layout: int = 1

    @classmethod
    def load(cls, path: Path) -> State:
        if not path.exists():
            return cls(path)
        raw = json.loads(path.read_text())
        return cls(path, raw.get("numbers", {}), raw.get("health", {}), raw.get("layout", 1))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"layout": self.layout, "numbers": self.numbers, "health": self.health},
                indent=1,
                sort_keys=True,
            )
        )

    def reserved(self, active: set[str], now: float | None = None) -> set[int]:
        now = now or time.time()
        return {
            rec["number"]
            for slug, rec in self.numbers.items()
            if slug not in active and now - rec["seen"] < RESERVE_SECONDS
        }

    def remember(self, slug: str, number: int, now: float | None = None) -> None:
        self.numbers[slug] = {"number": number, "seen": now or time.time()}

    def prune(self, now: float | None = None) -> None:
        now = now or time.time()
        self.numbers = {s: r for s, r in self.numbers.items() if now - r["seen"] < RESERVE_SECONDS}

    def record_health(self, slug: str, ok: bool, label: str, now: float | None = None) -> None:
        history = self.health.setdefault(slug, [])
        history.append([int(now or time.time()), ok, label])
        del history[:-HISTORY]

    def uptime(self, slug: str) -> float | None:
        history = self.health.get(slug)
        if not history:
            return None
        return sum(1 for _, ok, _ in history if ok) / len(history)

    def relayout(self, layout: int) -> None:
        """A new region layout moves the blocks, so old numbers no longer apply."""
        if layout != self.layout:
            self.numbers = {}
            self.layout = layout
