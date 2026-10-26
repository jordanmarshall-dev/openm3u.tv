from __future__ import annotations

import json
import logging
from datetime import datetime

from ..fetch import Fetcher
from ..guide import read_guide
from ..models import Channel
from .base import Source

log = logging.getLogger(__name__)

BASE = "https://i.mjh.nz"
PLAYBACK = "https://jmp2.uk/"
SERVICES = {"samsung": "SamsungTVPlus", "pluto": "PlutoTV"}
SLUGS = {"SamsungTVPlus": "stvp-{id}", "PlutoTV": "plu-{id}.m3u8"}


class Fast(Source):
    """Samsung TV Plus or Pluto TV, from Matt Huisman's public feeds (i.mjh.nz).

    Playback goes through jmp2.uk, his redirect service, which hands out a fresh
    stream link each time a channel is tuned. Nothing is proxied through us."""

    def __init__(self, name: str, service: str, region: str, fetcher: Fetcher, base: str = BASE):
        super().__init__()
        service = SERVICES.get(service, service)
        if service not in SLUGS:
            raise ValueError(f"unsupported service {service!r}, expected one of {list(SERVICES)}")
        self.name = name
        self.service = service
        self.region = region
        self.fetcher = fetcher
        self.base = base.rstrip("/")

    def channels(self) -> list[Channel]:
        data = json.loads(self.fetcher.bytes(f"{self.base}/{self.service}/.channels.json.gz"))
        region = data["regions"].get(self.region)
        if region is None:
            log.warning("%s has no %s feed", self.service, self.region)
            return []
        slug = data.get("slug", SLUGS[self.service])

        channels = []
        for channel_id, row in region["channels"].items():
            channel = Channel(
                source=self.name,
                source_id=channel_id,
                name=row["name"].strip(),
                url=PLAYBACK + slug.format(id=channel_id),
                labels=[row["group"]] if row.get("group") else [],
                number=_int(row.get("chno")),
                logo=row.get("logo"),
                description=(row.get("description") or "").strip() or None,
            )
            if row.get("license_url"):
                self.drop("drm", channel)
            else:
                channels.append(channel)
        log.info("%s %s: %d channels", self.name, self.region, len(channels))
        return channels

    def schedule(self, channels: list[Channel], start: datetime, stop: datetime) -> None:
        url = f"{self.base}/{self.service}/{self.region}.xml.gz"
        guide = read_guide(self.fetcher.bytes(url), start, stop)
        for channel in channels:
            channel.programs = guide.programs.get(channel.source_id, [])


class FreeToAir(Source):
    """Broadcast channels from Matt's Australian and New Zealand feeds, e.g.
    "au/Sydney" or "nz". Some streams need a particular user agent, which is
    passed along to the player."""

    def __init__(self, name: str, path: str, fetcher: Fetcher, base: str = BASE):
        super().__init__()
        self.name = name
        self.path = path.strip("/")
        self.fetcher = fetcher
        self.base = base.rstrip("/")

    def channels(self) -> list[Channel]:
        data = json.loads(self.fetcher.bytes(f"{self.base}/{self.path}/tv.json.gz"))
        channels = []
        for channel_id, row in data.items():
            if not row.get("mjh_master"):
                continue
            headers = {k.lower(): v for k, v in (row.get("headers") or {}).items() if v.strip()}
            number = _int(row.get("chno"))
            channel = Channel(
                source=self.name,
                source_id=row.get("epg_id") or channel_id,
                name=row["name"].strip(),
                url=row["mjh_master"],
                labels=["Free to air"] if number else [],
                number=number,
                logo=row.get("logo"),
                description=(row.get("description") or "").strip() or None,
                headers=headers,
            )
            if row.get("license_url"):
                self.drop("drm", channel)
            else:
                channels.append(channel)
        log.info("%s %s: %d channels", self.name, self.path, len(channels))
        return channels

    def schedule(self, channels: list[Channel], start: datetime, stop: datetime) -> None:
        guide = read_guide(self.fetcher.bytes(f"{self.base}/{self.path}/epg.xml.gz"), start, stop)
        for channel in channels:
            channel.programs = guide.programs.get(channel.source_id, [])


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
