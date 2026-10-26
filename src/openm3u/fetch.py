from __future__ import annotations

import gzip
import os
from pathlib import Path

import httpx

USER_AGENT = "openm3u (+https://github.com/jordanmarshall-dev/openm3u.tv)"


class Fetcher:
    """Reads a URL or a local path, transparently un-gzipping.

    `mirrors` rewrites URL prefixes, e.g. {"https://i.mjh.nz": "/data/i.mjh.nz"},
    which is how the tests and offline runs point sources at local copies."""

    def __init__(self, client: httpx.Client | None = None, mirrors: dict[str, str] | None = None):
        self.client = client or httpx.Client(
            timeout=60, follow_redirects=True, headers={"user-agent": USER_AGENT}
        )
        self.mirrors = mirrors or {}
        self._cache: dict[str, bytes] = {}

    def bytes(self, location: str) -> bytes:
        location = self.resolve(location)
        if location not in self._cache:
            if location.startswith(("http://", "https://")):
                headers = {}
                token = os.environ.get("GITHUB_TOKEN")
                if token and location.startswith("https://api.github.com/"):
                    headers["authorization"] = f"Bearer {token}"
                response = self.client.get(location, headers=headers)
                response.raise_for_status()
                data = response.content
            else:
                data = Path(location).expanduser().read_bytes()
            if data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            self._cache[location] = data
        return self._cache[location]

    def text(self, location: str) -> str:
        return self.bytes(location).decode("utf-8", errors="replace")

    def resolve(self, location: str) -> str:
        for prefix, replacement in self.mirrors.items():
            if location.startswith(prefix):
                return replacement + location[len(prefix) :]
        return location
