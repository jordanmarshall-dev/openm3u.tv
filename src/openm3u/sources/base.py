from __future__ import annotations

from datetime import datetime

from ..models import Channel


class Source:
    """Something that lists channels: who they are, where they stream, and
    usually what's on. Sources that can't vouch for their channels set
    `require_guide`, so only ones with listings make the lineup."""

    name: str
    require_guide = False

    def __init__(self) -> None:
        self.removed: dict[str, list[Channel]] = {}

    def channels(self) -> list[Channel]:
        raise NotImplementedError

    def schedule(self, channels: list[Channel], start: datetime, stop: datetime) -> None:
        pass

    def drop(self, why: str, channel: Channel) -> None:
        self.removed.setdefault(why, []).append(channel)
