from __future__ import annotations

import json
import logging

from .fetch import Fetcher
from .models import Channel
from .text import slugify, unbranded

log = logging.getLogger(__name__)

TREE = "https://api.github.com/repos/tv-logo/tv-logos/git/trees/main?recursive=1"
RAW = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/"
SUFFIXES = {
    "canada": "ca",
    "united-states": "us",
    "united-kingdom": "uk",
    "australia": "au",
    "new-zealand": "nz",
}


class LogoLibrary:
    """Clean, transparent channel logos from the tv-logo/tv-logos project.

    Files are named after the channel, like countries/canada/ctv-news-ca.png, so a
    channel's name is enough to find its logo. Only exact name matches are used."""

    def __init__(self, fetcher: Fetcher, countries: list[str]):
        self.countries = countries
        self.paths: set[str] = set()
        try:
            tree = json.loads(fetcher.bytes(TREE))["tree"]
        except Exception as exc:
            log.warning("logo library unavailable: %s", exc)
            return
        self.paths = {item["path"] for item in tree if item["path"].endswith(".png")}

    def find(self, name: str) -> str | None:
        stems = []
        for variant in (name, unbranded(name), name.removesuffix(" Channel")):
            stem = slugify(variant)
            if stem not in stems:
                stems.append(stem)
        for country in self.countries:
            suffix = SUFFIXES.get(country, "")
            for stem in stems:
                path = f"countries/{country}/{stem}-{suffix}.png"
                if path in self.paths:
                    return RAW + path
        return None


def is_tile(url: str | None) -> bool:
    """Logos baked onto a square background (Samsung's are) look boxy in a guide."""
    return bool(url) and "square" in url.lower()


def improve(channels: list[Channel], library: LogoLibrary, duplicates: dict[str, list]) -> int:
    """Swap in a clean logo where one exists: the library first, then a cleaner
    logo from another service carrying the same channel."""
    changed = 0
    for channel in channels:
        better = library.find(channel.name)
        if not better and (not channel.logo or is_tile(channel.logo)):
            better = next(
                (
                    other.logo
                    for other in duplicates.get(channel.key, [])
                    if other.logo and not is_tile(other.logo)
                ),
                None,
            )
        if better and better != channel.logo:
            channel.logo = better
            changed += 1
    log.info("logos: %d improved", changed)
    return changed
