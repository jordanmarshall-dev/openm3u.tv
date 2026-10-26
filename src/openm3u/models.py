from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Program:
    start: datetime
    stop: datetime
    title: str
    subtitle: str | None = None
    description: str | None = None
    season: int | None = None
    episode: int | None = None
    kind: str | None = None
    series_id: str | None = None
    categories: list[str] = field(default_factory=list)
    rating: str | None = None
    art: str | None = None
    year: int | None = None

    @property
    def seconds(self) -> float:
        return (self.stop - self.start).total_seconds()


@dataclass(frozen=True)
class StreamReport:
    ok: bool
    reason: str | None = None
    height: int = 0
    bandwidth: int = 0

    @property
    def label(self) -> str:
        if not self.ok:
            return self.reason or "failed"
        if self.height:
            return f"{self.height}p"
        return self.reason or "ok"


@dataclass
class Channel:
    source: str
    source_id: str
    name: str
    url: str = ""
    labels: list[str] = field(default_factory=list)
    number: int | None = None
    logo: str | None = None
    description: str | None = None
    language: str | None = None
    area: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    programs: list[Program] = field(default_factory=list)
    report: StreamReport | None = None
    guide_id: str = ""
    call_sign: str = ""
    # Picked by name in a region file, so it's carried even without a guide.
    curated: bool = False

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"


@dataclass
class Entry:
    channel: Channel
    slug: str
    group: str
    number: int = 0
