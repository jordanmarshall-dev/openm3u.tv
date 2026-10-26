from openm3u.dedupe import dedupe
from openm3u.models import StreamReport

from .factories import channel

HD = StreamReport(True, height=1080, bandwidth=5_000_000)
SD = StreamReport(True, height=720, bandwidth=2_500_000)
DEAD = StreamReport(False, "http 404")


def test_highest_quality_copy_wins():
    pluto = channel("CBS News 24/7", "pluto", report=SD)
    samsung = channel("CBS News 24/7", "samsung", report=HD)
    kept, dupes = dedupe([pluto, samsung])
    assert kept == [samsung]
    assert dupes[0].dropped == [pluto]


def test_working_stream_beats_better_dead_one():
    dead = channel("Bloomberg TV+", "samsung", report=StreamReport(False, "timeout", 1080, 9))
    alive = channel("Bloomberg TV+", "pluto", report=SD)
    kept, _ = dedupe([dead, alive])
    assert kept == [alive]


def test_source_priority_breaks_quality_ties():
    a = channel("Weather", "plex", report=HD)
    b = channel("Weather", "pluto", report=HD)
    kept, _ = dedupe([a, b], priority=["pluto", "plex"])
    assert kept == [b]


def test_names_are_compared_loosely_and_aliases_apply():
    a = channel("Bloomberg TV+ HD", "pluto", report=SD)
    b = channel("bloomberg tv +", "samsung", report=HD)
    c = channel("CBS News", "pluto", report=SD)
    d = channel("CBS News 24/7", "samsung", report=HD)
    kept, _ = dedupe([a, b, c, d], aliases={"CBS News 24/7": "CBS News"})
    assert kept == [b, d]


def test_branded_genre_channels_are_not_merged():
    kept, dupes = dedupe([channel("Pluto TV Comedy", "pluto"), channel("Plex Comedy", "plex")])
    assert len(kept) == 2
    assert not dupes


def test_original_order_is_preserved():
    channels = [channel(n) for n in ("C", "A", "B")]
    kept, _ = dedupe(channels)
    assert [c.name for c in kept] == ["C", "A", "B"]


def test_aliased_duplicates_take_the_alias_name():
    a = channel("MovieSphere", "samsung", report=HD)
    b = channel("MovieSphere by Lionsgate", "pluto", report=SD)
    kept, _ = dedupe([a, b], aliases={"MovieSphere": "MovieSphere by Lionsgate"})
    assert kept == [a]
    assert a.name == "MovieSphere by Lionsgate"
