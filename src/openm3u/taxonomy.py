from __future__ import annotations

import tomllib
from collections import Counter
from dataclasses import dataclass, field, replace
from importlib import resources

from .models import Channel
from .text import fold

OVERFLOW = 2000


@dataclass
class Group:
    id: str
    name: str
    start: int
    size: int = 100
    live: bool = False
    sort: str = "source"
    keep_small: bool = False
    keep_numbers: bool = False
    language: str | None = None
    labels: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)

    @property
    def numbers(self) -> range:
        return range(self.start, self.start + self.size)

    def overflow(self, tier: int) -> range:
        """A group that outgrows its range continues 2000 higher, then 4000 higher:
        News at 100, then 2100. Every group's tiers line up without colliding."""
        start = self.start + OVERFLOW * tier
        return range(start, start + self.size)

    def owns(self, number: int) -> bool:
        return number >= self.start and (number - self.start) % OVERFLOW < self.size


@dataclass
class Taxonomy:
    groups: list[Group]
    fallback: str
    series: str
    labels: dict[str, str] = field(default_factory=dict)
    skip: dict[str, str] = field(default_factory=dict)
    languages: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for group in self.groups:
            for label in group.labels:
                self.labels.setdefault(fold(label), group.id)

    def group(self, group_id: str) -> Group:
        for group in self.groups:
            if group.id == group_id:
                return group
        raise KeyError(group_id)

    def has(self, group_id: str) -> bool:
        return any(g.id == group_id for g in self.groups)

    def classify(self, labels: list[str], source: str = "") -> tuple[str | None, str | None]:
        """(group id, skip reason) for a channel's labels. The first label that
        means something wins, so a source's own ordering of categories counts."""
        for label in labels:
            key = fold(label)
            for lookup in (f"{source}:{key}", key):
                if lookup in self.skip:
                    return None, self.skip[lookup]
                if lookup in self.labels:
                    return self.labels[lookup], None
        return None, None

    def language(self, labels: list[str]) -> str | None:
        return next((self.languages[k] for k in map(fold, labels) if k in self.languages), None)

    def guess(self, channel: Channel) -> tuple[str | None, str | None]:
        """Classify a channel with no useful labels by what fills its guide, then
        by its name. "Trackside 1" is sports even with an empty schedule."""
        airtime: Counter[tuple] = Counter()
        for program in channel.programs:
            labels = [*program.categories, *(["movie"] if program.kind == "movie" else [])]
            for label in labels:
                found = self.classify([label])
                if any(found):
                    airtime[found] += program.seconds
                    break
        if airtime:
            return airtime.most_common(1)[0][0]
        words = f" {fold(channel.name)} "
        for group in self.groups:
            if any(f" {fold(hint)} " in words for hint in group.hints):
                return group.id, None
        return None, None

    def adjusted(
        self,
        overrides: dict[str, dict] | None = None,
        labels: dict[str, str] | None = None,
        extra: list[Group] | None = None,
    ) -> Taxonomy:
        """A region's copy: groups renamed or resized, labels sent elsewhere, and
        language blocks added at the end."""
        groups = []
        for group in self.groups:
            changes = (overrides or {}).get(group.id, {})
            unknown = set(changes) - {"name", "start", "size", "sort", "keep_numbers", "drop"}
            if unknown:
                raise ValueError(f"group {group.id!r} can't override {sorted(unknown)}")
            if changes.get("drop"):
                continue
            groups.append(replace(group, **{k: v for k, v in changes.items() if k != "drop"}))
        groups += extra or []
        taxonomy = Taxonomy(
            groups, self.fallback, self.series, {}, dict(self.skip), dict(self.languages)
        )
        for label, target in (labels or {}).items():
            source, _, name = label.rpartition(":")
            key = f"{source}:{fold(name)}" if source else fold(name)
            if target.startswith("skip:"):
                taxonomy.skip[key] = target.removeprefix("skip:")
            elif taxonomy.has(target):
                taxonomy.labels[key] = target
                taxonomy.skip.pop(key, None)
            else:
                raise ValueError(f"label {label!r} points at unknown group {target!r}")
        return taxonomy


def load_taxonomy() -> Taxonomy:
    raw = tomllib.loads(resources.files("openm3u").joinpath("taxonomy.toml").read_text())
    groups = [Group(**item) for item in raw["group"]]
    skip = {fold(label): reason for reason, labels in raw["skip"].items() for label in labels}
    languages = {fold(label): code for code, labels in raw["languages"].items() for label in labels}
    return Taxonomy(groups, raw["fallback"], raw["series"], {}, skip, languages)
