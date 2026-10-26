from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase

from ..fetch import Fetcher
from ..models import Channel
from ..text import slugify
from .base import Source

log = logging.getLogger(__name__)

ATTR = re.compile(r'([\w-]+)="([^"]*)"')
RESOLUTION = re.compile(r"\s*\((\d{3,4})p\)")
TAGS = re.compile(r"\s*\[([^\]]+)\]")
CALL_SIGN = re.compile(r"\s*\(([CKW][A-Z]{2,4}(?:-(?:DT|TV|HD|CD|LD)\d?)?)\)")


@dataclass
class Entry:
    name: str
    url: str
    attrs: dict[str, str]
    tags: set[str]
    height: int | None
    headers: dict[str, str]
    call_sign: str = ""


def parse_m3u(text: str) -> list[Entry]:
    entries = []
    pending: tuple[str, dict] | None = None
    headers: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            head, _, title = line.partition(",")
            pending = (title.strip(), dict(ATTR.findall(head)))
            headers = {}
        elif line.startswith("#EXTVLCOPT:"):
            key, _, value = line.removeprefix("#EXTVLCOPT:").partition("=")
            name = {"http-user-agent": "user-agent", "http-referrer": "referer"}.get(key)
            if name and value:
                headers[name] = value
        elif line and not line.startswith("#") and pending:
            title, attrs = pending
            tags = {t.lower() for t in TAGS.findall(title)}
            resolution = RESOLUTION.search(title)
            name = TAGS.sub("", RESOLUTION.sub("", title)).strip()
            sign = CALL_SIGN.search(name)
            if sign:
                name = CALL_SIGN.sub("", name).strip()
            entries.append(
                Entry(
                    name,
                    line,
                    attrs,
                    tags,
                    int(resolution.group(1)) if resolution else None,
                    headers,
                    sign.group(1).split("-")[0] if sign else "",
                )
            )
            pending = None
    return entries


def pick(name: str, include: dict[str, str]) -> str | None:
    """The label of the first pattern a name matches: {"CBC News*": "News"}."""
    for pattern, label in include.items():
        if fnmatchcase(name.lower(), pattern.lower()):
            return label
    return None


class Playlist(Source):
    """Any M3U. With `include`, only channels matching one of its name patterns
    are carried, each under the pattern's label; that's how a long community list
    becomes a short, curated one."""

    def __init__(
        self,
        name: str,
        url: str,
        fetcher: Fetcher,
        include: dict[str, str] | None = None,
        part_time: bool = False,
        require_guide: bool = False,
    ):
        super().__init__()
        self.name = name
        self.url = url
        self.fetcher = fetcher
        self.include = include or {}
        self.part_time = part_time
        self.require_guide = require_guide

    def channels(self) -> list[Channel]:
        channels: list[Channel] = []
        used: set[str] = set()
        for entry in parse_m3u(self.fetcher.text(self.url)):
            label = pick(entry.name, self.include)
            if self.include and label is None:
                continue
            channel = to_channel(self.name, entry, used)
            channel.curated = label is not None
            group_title = entry.attrs.get("group-title", "")
            channel.labels = [label] if label else [g for g in group_title.split(";") if g]
            if "not 24/7" in entry.tags and not self.part_time:
                self.drop("part-time", channel)
                continue
            channels.append(channel)
        log.info("%s: %d channels", self.name, len(channels))
        return channels


def to_channel(source: str, entry: Entry, used: set[str]) -> Channel:
    tvg_id = entry.attrs.get("tvg-id", "")
    source_id = tvg_id or slugify(entry.name)
    if source_id in used:
        source_id = f"{source_id}#{len(used)}"
    used.add(source_id)
    return Channel(
        source=source,
        source_id=source_id,
        name=entry.name,
        url=entry.url,
        logo=entry.attrs.get("tvg-logo") or None,
        headers=entry.headers,
        guide_id=tvg_id,
        call_sign=entry.call_sign,
    )
