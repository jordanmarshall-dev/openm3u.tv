from datetime import timedelta

from openm3u.language import detect
from openm3u.models import Program

from .factories import T0, channel


def guide(*lines):
    return [
        Program(T0 + timedelta(hours=i), T0 + timedelta(hours=i + 1), title, description=desc)
        for i, (title, desc) in enumerate(lines)
    ]


def test_french_guide_text_is_detected():
    ch = channel(
        "Kids Corner",
        programs=guide(
            ("Les aventures de Tintin", "Tintin et son chien partent pour une nouvelle mission."),
            ("Caillou", "Caillou passe la journée avec les enfants du quartier."),
        ),
    )
    assert detect(ch) == "fr"


def test_english_guide_text_stays_english():
    ch = channel(
        "Kids Corner",
        programs=guide(("Arthur", "Arthur and his friends go to the fair with the family.")),
    )
    assert detect(ch) == "en"


def test_names_and_categories_decide_first():
    assert detect(channel("Radio-Canada INFO")) == "fr"
    assert detect(channel("Nick Jr.", label="Kids en Français")) == "fr"


def test_a_stray_french_title_does_not_flip_an_english_channel():
    ch = channel(
        "Pluto TV Drama Movies",
        programs=guide(
            ("La Femme Nikita", "A young woman is recruited by a secret agency in the city."),
            ("Heat", "A detective hunts a thief and his crew across the city."),
        ),
    )
    assert detect(ch) == "en"


def test_empty_guide_falls_back_to_the_region_language():
    assert detect(channel("Mystery Channel")) == "en"
