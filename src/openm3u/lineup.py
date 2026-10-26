from __future__ import annotations

import logging
import time
from collections import Counter

from .models import Channel, Entry
from .regions import Region
from .state import State
from .text import fold, slugify, unbranded

log = logging.getLogger(__name__)


def assign_groups(
    channels: list[Channel],
    region: Region,
    groups: dict[str, str],
    overrides: dict[str, str] | None = None,
) -> list[Entry]:
    """Turn classified channels into lineup entries. `groups` maps channel keys to
    group ids; `overrides` are the user's "this channel goes there" by name.
    Groups too small to be worth a heading fold into the fallback."""
    by_id = {g.id: g for g in region.groups}
    by_name = {fold(g.name): g.id for g in region.groups}
    pinned = {}
    for name, target in (overrides or {}).items():
        group_id = target if target in by_id else by_name.get(fold(target))
        if group_id:
            pinned[fold(name)] = group_id
        else:
            log.warning("ignoring group override %r -> %r: no such group", name, target)

    fallback = region.taxonomy.fallback
    entries = []
    for channel in channels:
        group = pinned.get(fold(channel.name)) or groups.get(channel.key) or fallback
        entries.append(Entry(channel, "", group if group in by_id else fallback))

    sizes = Counter(e.group for e in entries)
    keep = set(pinned.values()) | {g.id for g in region.groups if g.keep_small}
    for entry in entries:
        if sizes[entry.group] < region.min_group_size and entry.group not in keep:
            entry.group = fallback

    used: set[str] = set()
    for entry in entries:
        base = slug = slugify(entry.channel.name)
        n = 2
        while slug in used:
            slug, n = f"{base}-{n}", n + 1
        used.add(slug)
        entry.slug = slug
    return entries


def assign_numbers(
    entries: list[Entry],
    region: Region,
    state: State,
    pinned: dict[str, int] | None = None,
    sources: list[str] | None = None,
    now: float | None = None,
) -> list[Entry]:
    """Give every entry a channel number that stays put between builds.

    Numbers come from, in order: the user's pins, the channel's own number where
    its group keeps broadcast numbers (Seven on 7 in Australia), the number it
    had last time if it's still in the right group, then the next free slot.
    Numbers of channels that vanish are held for 30 days so they don't get
    handed to something else while the channel is briefly offline."""
    now = now or time.time()
    pins = {fold(name): number for name, number in (pinned or {}).items()}
    order = {g.id: i for i, g in enumerate(region.groups)}
    sources = sources or []

    def position(entry: Entry) -> tuple:
        group = region.group(entry.group)
        channel = entry.channel
        name = unbranded(channel.name)
        if group.sort == "name":
            return (order[group.id], 0, "", 0, 0, 0, name)
        place = (0, "")
        if group.sort == "place":
            place = (region.place(f"{channel.name} {channel.area}"), fold(channel.area))
        source = sources.index(channel.source) if channel.source in sources else len(sources)
        number = channel.number if channel.number is not None else 1 << 30
        return (order[group.id], *place, region.prominence(channel.name), source, number, name)

    entries.sort(key=position)

    taken = state.reserved({e.slug for e in entries}, now)
    for entry in entries:
        entry.number = pins.get(fold(entry.channel.name), 0)
        if entry.number:
            taken.add(entry.number)

    for entry in entries:
        group = region.group(entry.group)
        own = entry.channel.number
        if not entry.number and group.keep_numbers and own in group.numbers and own not in taken:
            entry.number = own
            taken.add(own)

    for entry in entries:
        if entry.number:
            continue
        previous = state.numbers.get(entry.slug, {}).get("number")
        if previous and region.group(entry.group).owns(previous) and previous not in taken:
            entry.number = previous
            taken.add(previous)

    for entry in entries:
        if not entry.number:
            entry.number = _next_free(region, entry.group, taken)
            taken.add(entry.number)

    for entry in entries:
        state.remember(entry.slug, entry.number, now)
    state.prune(now)
    entries.sort(key=lambda e: e.number)
    return entries


def _next_free(region: Region, group_id: str, taken: set[int]) -> int:
    group = region.group(group_id)
    for tier in range(10):
        free = next((n for n in group.overflow(tier) if n not in taken), None)
        if free is not None:
            if tier:
                log.info("%s is past its range, continuing at %d", group.name, free)
            return free
    return max(taken) + 1
