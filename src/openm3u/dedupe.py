from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .models import Channel, StreamReport
from .text import channel_key

UNCHECKED = StreamReport(True)


@dataclass
class Duplicate:
    kept: Channel
    dropped: list[Channel]


def rank(channel: Channel, priority: list[str]) -> tuple:
    report = channel.report or UNCHECKED
    source_rank = -priority.index(channel.source) if channel.source in priority else -len(priority)
    return (report.ok, report.height, report.bandwidth, source_rank, len(channel.programs))


def dedupe(
    channels: list[Channel],
    aliases: dict[str, str] | None = None,
    priority: list[str] | None = None,
) -> tuple[list[Channel], list[Duplicate]]:
    folded = {channel_key(k): channel_key(v) for k, v in (aliases or {}).items()}
    groups: dict[str, list[Channel]] = defaultdict(list)
    for channel in channels:
        key = channel_key(channel.name)
        groups[folded.get(key, key)].append(channel)

    names = {channel_key(v): v for v in (aliases or {}).values()}
    kept, duplicates = [], []
    for key, members in groups.items():
        members.sort(key=lambda c: rank(c, priority or []), reverse=True)
        if key in names and len(members) > 1:
            members[0].name = names[key]
        kept.append(members[0])
        if len(members) > 1:
            duplicates.append(Duplicate(members[0], members[1:]))
    order = {id(c): i for i, c in enumerate(channels)}
    kept.sort(key=lambda c: order[id(c)])
    return kept, duplicates
