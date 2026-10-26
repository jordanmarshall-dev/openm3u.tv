from openm3u.lineup import assign_groups, assign_numbers
from openm3u.regions import load_region
from openm3u.state import RESERVE_SECONDS, State

from .factories import channel

CA = load_region("ca")
NOW = 1_800_000_000.0


def classified(channels):
    return {c.key: CA.taxonomy.classify(c.labels)[0] for c in channels}


def entries(channels, overrides=None):
    return assign_groups(channels, CA, classified(channels), overrides)


def lineup(channels, state, pins=None, overrides=None, now=NOW):
    found = entries(channels, overrides)
    return {e.channel.name: e for e in assign_numbers(found, CA, state, pins, now=now)}


def news(n):
    return [channel(f"News {i}", label="News + Opinion", number=i) for i in range(n)]


def test_labels_map_to_cable_groups():
    found = entries(
        news(3)
        + [
            channel("Ink Master", label="Competition Reality"),
            channel("Reality A", label="Reality"),
            channel("Reality B", label="Reality"),
        ]
    )
    groups = {e.channel.name: e.group for e in found}
    assert groups["News 0"] == "news"
    assert groups["Ink Master"] == "reality"


def test_tiny_groups_fold_into_the_fallback():
    found = entries(news(3) + [channel("Lonely Doc", label="Documentary + Science")])
    groups = {e.channel.name: e.group for e in found}
    assert groups["Lonely Doc"] == "entertainment"
    assert groups["News 0"] == "news"


def test_unknown_label_goes_to_fallback():
    assert entries([channel("Mystery", label="Something New")])[0].group == "entertainment"


def test_numbers_land_in_the_group_block(tmp_path):
    result = lineup(news(3), State(tmp_path / "s.json"))
    assert [result[f"News {i}"].number for i in range(3)] == [100, 101, 102]


def test_numbers_are_stable_when_channels_come_and_go(tmp_path):
    state = State(tmp_path / "s.json")
    first = lineup(news(4), state)
    assert first["News 3"].number == 103

    channels = news(4)
    del channels[1]
    channels.insert(0, channel("Breaking", label="News + Opinion", number=-1))
    second = lineup(channels, state, now=NOW + 3600)
    assert second["News 0"].number == 100
    assert second["News 2"].number == 102
    assert second["News 3"].number == 103
    assert second["Breaking"].number == 104

    third = lineup(news(4), state, now=NOW + 7200)
    assert third["News 1"].number == 101


def test_vanished_number_is_released_after_the_reserve_window(tmp_path):
    state = State(tmp_path / "s.json")
    lineup(news(4), state)
    later = NOW + RESERVE_SECONDS + 1
    newcomer = channel("Newcomer", label="News + Opinion", number=5)
    result = lineup([*news(3), newcomer], state, now=later)
    assert result["Newcomer"].number == 103


def test_pins_and_group_overrides(tmp_path):
    channels = news(3) + [channel("APTN Beyond", label="New on Pluto TV")]
    result = lineup(
        channels,
        State(tmp_path / "s.json"),
        pins={"News 2": 100},
        overrides={"APTN Beyond": "Lifestyle & Documentary"},
    )
    assert result["News 2"].number == 100
    assert result["News 0"].number == 101
    assert result["APTN Beyond"].group == "lifestyle"
    assert result["APTN Beyond"].number == 800


def test_a_full_group_continues_two_thousand_higher(tmp_path):
    state = State(tmp_path / "s.json")
    result = lineup(news(102), state)
    assert result["News 99"].number == 199
    assert result["News 100"].number == 2100
    assert result["News 100"].group == "news"
    again = lineup(news(102), state, now=NOW + 60)
    assert again["News 101"].number == 2101


def test_state_round_trips(tmp_path):
    path = tmp_path / "ca.json"
    state = State(path)
    lineup(news(3), state)
    state.record_health("news-0", True, "1080p", NOW)
    state.record_health("news-0", False, "timeout", NOW)
    state.save()
    loaded = State.load(path)
    assert loaded.numbers["news-1"]["number"] == 101
    assert loaded.uptime("news-0") == 0.5


def test_news_runs_national_first_then_west_to_east(tmp_path):
    names = [
        "Global News Halifax",
        "CBC News BC",
        "CTV News",
        "Global News Calgary",
        "Global News BC",
        "Bloomberg TV+",
        "CBC News Network",
    ]
    channels = [channel(n, label="News + Opinion", number=i) for i, n in enumerate(names)]
    result = lineup(channels, State(tmp_path / "s.json"))
    order = [name for name, _ in sorted(result.items(), key=lambda kv: kv[1].number)]
    assert order == [
        "CBC News Network",
        "CTV News",
        "Bloomberg TV+",
        "CBC News BC",
        "Global News BC",
        "Global News Calgary",
        "Global News Halifax",
    ]


def test_a_new_layout_resets_old_numbers(tmp_path):
    state = State(tmp_path / "s.json", numbers={"news-0": {"number": 140, "seen": NOW}})
    state.relayout(CA.layout)
    result = lineup(news(3), state)
    assert result["News 0"].number == 100
