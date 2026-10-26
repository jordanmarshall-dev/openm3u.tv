from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import datetime, timedelta

import httpx

from .fetch import Fetcher
from .guide import Guide, read_guide
from .models import Channel
from .text import fold

log = logging.getLogger(__name__)


def match_guides(
    channels: list[Channel],
    locations: list[str],
    fetcher: Fetcher,
    start: datetime,
    stop: datetime,
    names: dict[str, str] | None = None,
    failed: list[str] | None = None,
) -> tuple[int, int]:
    """Fill in listings from the region's guides.

    Channels with nothing get a schedule. Channels whose own guide runs out early
    (Samsung's only goes a few hours ahead) are continued from another guide that
    carries the same channel further. Guides are read one at a time and dropped,
    so a dozen of them never sit in memory together. Returns (channels listed,
    channels extended); guides that couldn't be read are added to `failed`."""
    names = {fold(k): v for k, v in (names or {}).items()}
    listed = extended = 0
    for location in locations:
        waiting = [c for c in channels if runs_out(c, stop)]
        if not waiting:
            break
        try:
            guide = read_guide(fetcher.bytes(location), start, stop)
        except (httpx.HTTPError, OSError, ET.ParseError) as exc:
            log.warning("skipping guide %s: %s", location, exc)
            if failed is not None:
                failed.append(location)
            continue
        index = _index(guide)
        for channel in waiting:
            guide_id = _match(channel, guide, index, names)
            if guide_id is None:
                continue
            last = max((p.stop for p in channel.programs), default=None)
            more = [p for p in guide.programs[guide_id] if last is None or p.start >= last]
            if not more:
                continue
            if channel.programs:
                extended += 1
            else:
                listed += 1
                channel.logo = channel.logo or guide.icons.get(guide_id)
            channel.programs = [*channel.programs, *more]
    return listed, extended


def runs_out(channel: Channel, stop: datetime, slack: timedelta = timedelta(hours=2)) -> bool:
    """True when a channel's listings end well before the guide window does."""
    last = max((p.stop for p in channel.programs), default=None)
    return last is None or last < stop - slack


def borrow(channels: list[Channel], siblings: dict[str, str]) -> int:
    """A station with no listings borrows a sibling's: CBC stations carry the
    same network schedule apart from local news."""
    siblings = {fold(k): fold(v) for k, v in siblings.items()}
    by_name = {fold(c.name): c for c in channels}
    borrowed = 0
    for channel in channels:
        sibling = by_name.get(siblings.get(fold(channel.name), ""))
        if not channel.programs and sibling and sibling.programs:
            channel.programs = [replace(p) for p in sibling.programs]
            borrowed += 1
    return borrowed


def guide_key(label: str) -> str:
    """Make "CBC.Vancouver.HD.ca2" compare equal to "CBC Vancouver"."""
    label = re.sub(r"\.[a-z]{2}\d*$", "", label)
    return re.sub(r"( hd| hdtv)+$", "", fold(label))


def _index(guide: Guide) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for guide_id, labels in guide.names.items():
        if not guide.programs.get(guide_id):
            continue
        for key in {guide_key(guide_id), *map(guide_key, labels)}:
            index.setdefault(key, []).append(guide_id)
    return index


def _match(
    channel: Channel, guide: Guide, index: dict[str, list[str]], names: dict[str, str]
) -> str | None:
    """Find a channel in a guide: its own guide id, then its call sign (CBUT finds
    "CBC (CBUT) Vancouver, BC"), then a name from the region file, then its name."""
    if channel.guide_id and guide.programs.get(channel.guide_id):
        return channel.guide_id

    def busiest(ids):
        return max(
            ids, key=lambda i: (guide.programs[i][-1].stop, len(guide.programs[i])), default=None
        )

    if channel.call_sign:
        sign = re.compile(rf"\b{channel.call_sign}(?:HD|-DT|-TV)?\b")
        hit = busiest(
            gid
            for gid, labels in guide.names.items()
            if guide.programs.get(gid) and (sign.search(gid) or any(map(sign.search, labels)))
        )
        if hit:
            return hit

    wanted = guide_key(names.get(fold(channel.name), channel.name))
    return busiest(index.get(wanted, []))
