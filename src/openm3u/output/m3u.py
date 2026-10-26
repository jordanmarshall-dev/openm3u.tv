from __future__ import annotations

from collections.abc import Callable

from ..models import Entry


def _attr(value: str | int | None) -> str:
    return str(value or "").replace('"', "'").replace("\n", " ")


def render_m3u(
    entries: list[Entry],
    region: str,
    group_name: Callable[[Entry], str] = lambda entry: entry.group,
    guide_url: str = "",
) -> str:
    header = "#EXTM3U"
    if guide_url:
        header += f' x-tvg-url="{_attr(guide_url)}" url-tvg="{_attr(guide_url)}"'
    lines = [header]
    for entry in entries:
        channel = entry.channel
        lines.append(
            f'#EXTINF:-1 tvg-id="{entry.slug}.{region}" tvg-chno="{entry.number}" '
            f'tvg-name="{_attr(channel.name)}" tvg-logo="{_attr(channel.logo)}" '
            f'group-title="{_attr(group_name(entry))}",{channel.name}'
        )
        if agent := channel.headers.get("user-agent"):
            lines.append(f"#EXTVLCOPT:http-user-agent={agent}")
        if referer := channel.headers.get("referer"):
            lines.append(f"#EXTVLCOPT:http-referrer={referer}")
        lines.append(channel.url)
    return "\n".join(lines) + "\n"
