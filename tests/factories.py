from datetime import UTC, datetime, timedelta

from openm3u.models import Channel, Program, StreamReport

T0 = datetime(2026, 10, 24, 6, tzinfo=UTC)


def schedule(*titles: str, hours: float = 1, categories=()) -> list[Program]:
    programs = []
    start = T0
    for title in titles:
        stop = start + timedelta(hours=hours)
        programs.append(Program(start, stop, title, kind="episode", categories=list(categories)))
        start = stop
    return programs


def channel(
    name: str,
    source: str = "pluto",
    label: str | None = None,
    *,
    number: int | None = None,
    programs=(),
    report: StreamReport | None = None,
    source_id: str | None = None,
    url: str | None = None,
) -> Channel:
    source_id = source_id or name.lower().replace(" ", "-")
    return Channel(
        source=source,
        source_id=source_id,
        name=name,
        url=url or f"https://streams.example/{source}/{source_id}.m3u8",
        labels=[label] if label else [],
        number=number,
        programs=list(programs),
        report=report,
    )
