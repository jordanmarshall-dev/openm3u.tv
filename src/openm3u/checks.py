from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import Channel, StreamReport

DAY = 86400


@dataclass
class Check:
    name: str
    ok: bool
    label: str
    height: int = 0
    when: int = 0


@dataclass
class Checks:
    """Stream checks run from inside a country.

    The public builder runs in the US, where a Canadian or British stream that's
    limited to its own country just answers "forbidden". Someone in the country
    runs `openm3u verify`, commits the result, and the builder trusts it: streams
    that failed there are dropped, ones that played are marked verified."""

    region: str
    checked_from: str
    streams: dict[str, Check]

    @classmethod
    def load(cls, path: Path) -> Checks | None:
        if not path.exists():
            return None
        raw = json.loads(path.read_text())
        streams = {url: Check(**row) for url, row in raw.get("streams", {}).items()}
        return cls(raw["region"], raw.get("checked_from", raw["region"]), streams)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "region": self.region,
            "checked_from": self.checked_from,
            "streams": {url: asdict(check) for url, check in sorted(self.streams.items())},
        }
        path.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n")

    def record(self, channels: Iterable[Channel], now: float | None = None) -> None:
        when = int(now or time.time())
        for channel in channels:
            report = channel.report or StreamReport(False, "unchecked")
            self.streams[channel.url] = Check(
                channel.name, report.ok, report.label, report.height, when
            )

    def fresh(self, url: str, days: int, now: float | None = None) -> Check | None:
        check = self.streams.get(url)
        if check and (now or time.time()) - check.when < days * DAY:
            return check
        return None


def apply(
    channels: list[Channel], checks: Checks, days: int, now: float | None = None
) -> tuple[list[Channel], list[Channel]]:
    """Settle streams the builder couldn't test with a recent check from inside
    the country. Returns the channels confirmed there and the ones that failed."""
    confirmed, failed = [], []
    where = checks.checked_from.upper()
    for channel in channels:
        if not channel.report or channel.report.reason != "unverified":
            continue
        check = checks.fresh(channel.url, days, now)
        if check is None:
            continue
        if check.ok:
            channel.report = StreamReport(True, f"checked in {where}", check.height)
            confirmed.append(channel)
        else:
            channel.report = StreamReport(False, f"{check.label} in {where}")
            failed.append(channel)
    return confirmed, failed
