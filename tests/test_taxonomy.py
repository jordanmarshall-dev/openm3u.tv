import pytest

from openm3u.regions import CODES, load_region
from openm3u.taxonomy import load_taxonomy

from .factories import channel, schedule

TAXONOMY = load_taxonomy()


@pytest.mark.parametrize(
    ("labels", "group"),
    [
        (["News & Opinion"], "news"),
        (["News + Opinion"], "news"),
        (["news"], "news"),
        (["Sports & Outdoors"], "sports"),
        (["Mixed Martial Arts"], "sports"),
        (["Classic TV Comedy"], "comedy"),
        (["Daytime + Game Shows"], "reality"),
        (["True Crime"], "crime"),
        (["Nature, History & Science"], "lifestyle"),
        (["Home + Food"], "lifestyle"),
        (["Kids en Français"], "kids"),
        (["Music & Ambient"], "music"),
        (["animation", "kids"], "kids"),
        (["Something Brand New"], None),
    ],
)
def test_every_sources_labels_land_in_one_group(labels, group):
    assert TAXONOMY.classify(labels)[0] == group


def test_shopping_religion_and_adult_are_skipped_with_a_reason():
    assert TAXONOMY.classify(["shop"]) == (None, "shopping")
    assert TAXONOMY.classify(["religious", "music"]) == (None, "religion")
    assert TAXONOMY.classify(["xxx"]) == (None, "adult")


def test_language_labels():
    assert TAXONOMY.language(["Latino"]) == "es"
    assert TAXONOMY.language(["Kids en Français"]) == "fr"
    assert TAXONOMY.language(["Kids"]) is None


def test_guessing_from_the_guide_then_the_name():
    sport = channel("Mystery Channel", programs=schedule("Match", "Replay", categories=["Rugby"]))
    assert TAXONOMY.guess(sport) == ("sports", None)
    assert TAXONOMY.guess(channel("DW English")) == ("news", None)
    assert TAXONOMY.guess(channel("Trackside 1")) == ("sports", None)
    assert TAXONOMY.guess(channel("The Groat")) == (None, None)


def test_groups_never_share_numbers_even_when_they_overflow():
    for code in CODES:
        region = load_region(code)
        owners = {}
        for group in region.groups:
            for tier in range(3):
                for number in group.overflow(tier):
                    assert number not in owners, (code, group.id, owners.get(number))
                    owners[number] = group.id
                    assert group.owns(number)


def test_regions_rename_groups_and_add_language_blocks():
    uk = load_region("uk")
    assert uk.group("local").name == "Freeview"
    au = load_region("au")
    assert au.group("local").keep_numbers
    ca = load_region("ca")
    assert ca.language_group("fr") == "lang-fr"
    assert ca.group("lang-fr").name == "En français"
    assert ca.group("lang-fr").start == 1400
    us = load_region("us")
    assert us.group(us.language_group("es")).name == "En español"


def test_a_region_can_send_a_label_elsewhere():
    taxonomy = TAXONOMY.adjusted(
        labels={"samsung:Entertainment": "comedy", "Auction": "skip:shopping"}
    )
    assert taxonomy.classify(["Entertainment"], "samsung") == ("comedy", None)
    assert taxonomy.classify(["Entertainment"], "pluto") == ("entertainment", None)
    assert taxonomy.classify(["Auction"]) == (None, "shopping")
    with pytest.raises(ValueError):
        TAXONOMY.adjusted(labels={"News": "nowhere"})
