from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from .models import Channel, StreamReport

log = logging.getLogger(__name__)

DRM_MARKERS = (
    "com.widevine",
    "edef8ba9-79d6-4ace-a3c8-27dcd51d21ed",
    "com.microsoft.playready",
    "9a04f079-9840-4286-ab92-e65be0885f95",
    "com.apple.streamingkeydelivery",
    "skd://",
    "method=sample-aes",
)
# Real playlists are a few kilobytes; anything past this is video.
PLAYLIST_LIMIT = 2_000_000
DEADLINE = 40
ATTR = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


@dataclass
class Variant:
    uri: str
    bandwidth: int = 0
    height: int = 0


def parse_master(text: str, base: str) -> list[Variant]:
    variants = []
    lines = [line.strip() for line in text.splitlines()]
    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        attrs = {k: v.strip('"') for k, v in ATTR.findall(line.split(":", 1)[1])}
        uri = next((u for u in lines[i + 1 :] if u and not u.startswith("#")), None)
        if uri is None:
            continue
        height = 0
        if "x" in attrs.get("RESOLUTION", ""):
            height = int(attrs["RESOLUTION"].split("x")[1] or 0)
        bandwidth = int(attrs.get("BANDWIDTH") or attrs.get("AVERAGE-BANDWIDTH") or 0)
        variants.append(Variant(urljoin(base, uri), bandwidth, height))
    return variants


def has_drm(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in DRM_MARKERS)


class Endless(Exception):
    """A "playlist" that's really a live video stream, or one that never finishes."""


def _get(client: httpx.Client, url: str, headers: dict, deadline: float) -> tuple[int, str, str]:
    """Fetch a playlist, giving up on anything too big or too slow to be one.
    Some links point straight at a never-ending video stream; reading those
    whole would hang the build."""
    with client.stream("GET", url, headers=headers) as response:
        if response.status_code != 200:
            return response.status_code, "", str(response.url)
        body = bytearray()
        for chunk in response.iter_bytes():
            body += chunk
            if len(body) > PLAYLIST_LIMIT or time.monotonic() > deadline:
                raise Endless
        return 200, body.decode("utf-8", errors="replace"), str(response.url)


def probe(
    client: httpx.Client, url: str, headers: dict | None = None, seconds: float = DEADLINE
) -> StreamReport:
    headers = headers or {}
    deadline = time.monotonic() + seconds
    try:
        status, text, where = _get(client, url, headers, deadline)
        if status != 200:
            return StreamReport(False, f"http {status}")
        if "<MPD" in text:
            return _dash(text)
        if "#EXTM3U" not in text:
            return StreamReport(False, "not a stream")
        if has_drm(text):
            return StreamReport(False, "drm")

        variants = parse_master(text, where)
        best = max(variants, key=lambda v: (v.height, v.bandwidth), default=None)
        if best:
            status, text, base = _get(client, best.uri, headers, deadline)
            if status != 200:
                return StreamReport(False, f"variant http {status}")
            if has_drm(text):
                return StreamReport(False, "drm")
        else:
            base = where

        segments = [
            line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")
        ]
        if not segments:
            return StreamReport(False, "no segments")

        with client.stream("GET", urljoin(base, segments[0]), headers=headers) as segment:
            if segment.status_code not in (200, 206):
                return StreamReport(False, f"segment http {segment.status_code}")
            next(segment.iter_bytes(4096), b"")

        return StreamReport(True, None, best.height if best else 0, best.bandwidth if best else 0)
    except Endless:
        return StreamReport(False, "not a playlist")
    except httpx.TimeoutException:
        return StreamReport(False, "timeout")
    except httpx.HTTPError as exc:
        return StreamReport(False, type(exc).__name__)


def check(
    channels: Iterable[Channel],
    client: httpx.Client,
    concurrency: int = 6,
    retries: int = 1,
) -> None:
    def run(channel: Channel) -> None:
        report = StreamReport(False, "unchecked")
        for _ in range(retries + 1):
            try:
                report = probe(client, channel.url, channel.headers)
            except Exception as exc:
                report = StreamReport(False, f"error: {exc}")
            if report.ok or report.reason == "drm":
                break
        channel.report = report
        log.debug("%s %s", report.label.ljust(12), channel.name)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(run, channels))


def _dash(manifest: str) -> StreamReport:
    """DASH manifests (the BBC uses them) are checked lightly: any content
    protection means DRM, otherwise the best video representation sets quality."""
    if "<ContentProtection" in manifest:
        return StreamReport(False, "drm")
    heights = [int(h) for h in re.findall(r'\bheight="(\d+)"', manifest)]
    rates = [int(b) for b in re.findall(r'\bbandwidth="(\d+)"', manifest)]
    if not heights and not rates:
        return StreamReport(False, "no segments")
    return StreamReport(True, None, max(heights, default=0), max(rates, default=0))
