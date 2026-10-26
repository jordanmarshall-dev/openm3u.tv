from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass
from datetime import date
from functools import cached_property

from ..fetch import Fetcher
from ..models import Channel
from .base import Source
from .playlist import parse_m3u, pick, to_channel

log = logging.getLogger(__name__)

STREAMS = "https://raw.githubusercontent.com/iptv-org/iptv/master/streams"
DATABASE = "https://raw.githubusercontent.com/iptv-org/database/master/data"
LANGUAGES = {"eng": "en", "fra": "fr", "spa": "es", "mri": "mi", "cym": "cy", "gla": "gd"}
FEED_SIGN = re.compile(r"^([CKW][A-Z]{2,4})(DT|TV|CD|LD|HD)?$")
# Categories that make a channel serving one city or province a local station.
# Stations with no category at all (CBC's, Radio-Canada's) count too.
STATION = {"general", "public", "entertainment", "family"}


@dataclass
class Listing:
    name: str
    categories: list[str]
    nsfw: bool
    closed: str
    blocked: str


@dataclass
class Feed:
    areas: list[str]
    languages: list[str]


class Database:
    """iptv-org's channel database: what each channel is, where it broadcasts,
    and which channels must never be listed (the blocklist covers channels
    removed at their owners' request, and adult content)."""

    def __init__(self, fetcher: Fetcher, base: str = DATABASE):
        self.fetcher = fetcher
        self.base = base.rstrip("/")

    def _rows(self, name: str) -> list[dict]:
        text = self.fetcher.text(f"{self.base}/{name}.csv")
        return list(csv.DictReader(io.StringIO(text)))

    @cached_property
    def channels(self) -> dict[str, Listing]:
        blocked = {row["channel"]: row["reason"] for row in self._rows("blocklist")}
        return {
            row["id"]: Listing(
                row["name"],
                [c for c in row["categories"].split(";") if c],
                row["is_nsfw"].upper() == "TRUE",
                row["closed"],
                blocked.get(row["id"], ""),
            )
            for row in self._rows("channels")
        }

    @cached_property
    def feeds(self) -> dict[tuple[str, str], Feed]:
        return {
            (row["channel"], row["id"]): Feed(
                [a for a in row["broadcast_area"].split(";") if a],
                [LANGUAGES.get(code, code) for code in row["languages"].split(";") if code],
            )
            for row in self._rows("feeds")
        }

    @cached_property
    def places(self) -> dict[str, str]:
        names = {f"s/{row['code']}": row["name"] for row in self._rows("subdivisions")}
        names.update({f"ct/{row['code']}": row["name"] for row in self._rows("cities")})
        return names


class IptvOrg(Source):
    """Streams from iptv-org's lists for one country, described by its database.

    Every stream file for a country can be read: the main one ("us") and the
    per-service ones ("us_tubi", "us_xumo", "uk_distro"). Channels matching
    `include` are carried by name; everything else must find a guide, which keeps
    the long tail of tiny stations out unless they're properly listed."""

    require_guide = True

    def __init__(
        self,
        name: str,
        country: str,
        files: list[str],
        fetcher: Fetcher,
        database: Database | None = None,
        include: dict[str, str] | None = None,
        base: str = STREAMS,
    ):
        super().__init__()
        self.name = name
        self.country = country.upper()
        self.files = files
        self.fetcher = fetcher
        self.database = database or Database(fetcher)
        self.include = include or {}
        self.base = base.rstrip("/")

    def channels(self) -> list[Channel]:
        channels: list[Channel] = []
        used: set[str] = set()
        today = date.today().isoformat()
        for file in self.files:
            try:
                text = self.fetcher.text(f"{self.base}/{file}.m3u")
            except Exception as exc:
                log.warning("skipping iptv-org %s: %s", file, exc)
                continue
            for entry in parse_m3u(text):
                channel = to_channel(self.name, entry, used)
                channel_id, _, feed_id = channel.guide_id.partition("@")
                listing = self.database.channels.get(channel_id)
                feed = self.database.feeds.get((channel_id, feed_id))
                label = pick(channel.name, self.include)

                if listing and listing.blocked:
                    self.drop("blocklisted", channel)
                    continue
                if listing and listing.nsfw:
                    self.drop("adult", channel)
                    continue
                if listing and listing.closed and listing.closed <= today:
                    self.drop("closed", channel)
                    continue
                if "not 24/7" in entry.tags and label is None:
                    self.drop("part-time", channel)
                    continue

                channel.curated = label is not None
                channel.area = self._area(feed)
                if feed and feed.languages:
                    channel.language = feed.languages[0]
                if not channel.call_sign and (sign := FEED_SIGN.match(feed_id)):
                    channel.call_sign = sign.group(1)
                categories = listing.categories if listing else []
                if "legislative" in categories and _city(feed):
                    categories = ["public access"]
                elif channel.area and (not categories or STATION & set(categories)):
                    categories = ["local", *categories]
                channel.labels = [label] if label else categories
                channels.append(channel)
        log.info("%s: %d channels from %d files", self.name, len(channels), len(self.files))
        return channels

    def _area(self, feed: Feed | None) -> str:
        """The places a feed serves, if it's narrower than the whole country."""
        if feed is None or f"c/{self.country}" in feed.areas:
            return ""
        return ", ".join(self.database.places[a] for a in feed.areas if a in self.database.places)


def _city(feed: Feed | None) -> bool:
    """City council and other municipal channels are public access, not TV."""
    return bool(feed) and any(area.startswith("ct/") for area in feed.areas)
