from datetime import timedelta

from openm3u.fetch import Fetcher
from openm3u.filters import apply_filters, dominance, is_single_show, matches
from openm3u.sources import Fast

from .conftest import MIRRORS
from .factories import T0, channel, schedule


def names(channels):
    return sorted(c.name for c in channels)


def pluto_channels():
    pluto = Fast("pluto", "pluto", "ca", Fetcher(mirrors=MIRRORS))
    channels = pluto.channels()
    start = T0.replace(hour=10)
    pluto.schedule(channels, start, start + timedelta(hours=24))
    return channels


def test_real_lineup_flags_one_show_loops():
    flagged = {c.name for c in pluto_channels() if is_single_show(c)}
    assert "Ink Master" in flagged
    assert "Pluto TV Action Movies" not in flagged


def test_genre_channel_running_a_marathon_today_is_kept():
    marathon = channel("Pluto TV Comedy", programs=schedule(*["Man With a Plan"] * 20))
    assert dominance(marathon).share == 1.0
    assert not is_single_show(marathon)


def test_genre_channel_with_one_show_all_weekend_is_caught():
    loop = channel("Pluto TV Comedy", programs=schedule(*["Man With a Plan"] * 48))
    assert is_single_show(loop)


def test_named_channel_needs_only_most_of_the_airtime():
    ink = channel("Ink Master", programs=schedule(*["Ink Master"] * 9, "Ink Master: Angels"))
    assert is_single_show(ink)


def test_punctuation_and_branding_do_not_hide_the_match():
    walker = channel("Walker Texas Ranger", programs=schedule(*["Walker, Texas Ranger"] * 6))
    ridiculous = channel("MTV Ridiculousness", programs=schedule(*["Ridiculousness"] * 6))
    assert is_single_show(walker)
    assert is_single_show(ridiculous)


def test_varied_schedule_is_kept():
    movies = channel("Thrillers 365", programs=schedule("Heat", "Ronin", "Collateral", "Heat"))
    assert not is_single_show(movies)


def test_keep_and_hide_lists():
    south_park = channel("South Park: Kyle Collection", programs=schedule(*["South Park"] * 48))
    ink = channel("Ink Master", programs=schedule(*["Ink Master"] * 10))
    cbs = channel("CBS News 24/7")
    visible, hidden, loops = apply_filters(
        [south_park, ink, cbs], hide=["CBS News 24/7"], keep=["South Park"]
    )
    assert names(hidden) == ["CBS News 24/7"]
    assert names(visible) == ["Ink Master", "South Park: Kyle Collection"]
    assert names(loops) == ["Ink Master"]


def test_hide_patterns_match_names_or_source_ids():
    cbc = channel("CBC Vancouver", "iptv-org", source_id="CBCTelevision.ca@CBUTDT")
    assert matches(cbc, ["CBCTelevision.ca@*"])
    assert matches(channel("BBC One (HEVC)"), ["*(HEVC)"])
    assert not matches(channel("CBC News"), ["CBCTelevision.ca@*"])


def test_exempt_channels_skip_the_one_show_check():
    news = channel(
        "Global News BC", label="Local News", programs=schedule(*["Global News BC"] * 30)
    )
    visible, _, loops = apply_filters([news], [], [], exempt=lambda c: "Local News" in c.labels)
    assert visible == [news]
    assert loops == []
