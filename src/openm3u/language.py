from __future__ import annotations

import re
from collections import Counter

from .models import Channel

WORDS = {
    "fr": set(
        "le la les des du une et est dans pour avec sur au aux qui que pas son ses leur cette "
        "nouvelles télé émission épisode français française enfants jeunesse".split()
    ),
    "es": set(
        "el los las del una con por para que es su sus noticias en y temporada capítulo "
        "niños películas".split()
    ),
    "en": set(
        "the and of to in with for on is his her their a an from news episode show after "
        "when who".split()
    ),
}
NAME_HINTS = {
    "fr": re.compile(r"\b(en français|radio-canada|ici rdi|télé|noovo|tva)\b", re.I),
    "es": re.compile(r"\b(en español|latino|telemundo|univision)\b", re.I),
}
TOKEN = re.compile(r"[a-zà-ÿ]+", re.I)


def detect(channel: Channel, default: str = "en") -> str:
    """Guess a channel's language: its name and labels when they say it outright,
    then what its source says, then its guide text. The guide's titles and
    descriptions vote with common function words, which is plenty to tell English
    from French or Spanish across a day of programming."""
    label = " ".join([channel.name, *channel.labels])
    for language, pattern in NAME_HINTS.items():
        if pattern.search(label):
            return language
    if channel.language:
        return channel.language

    votes: Counter[str] = Counter()
    for program in channel.programs:
        text = " ".join(filter(None, (program.title, program.subtitle, program.description)))
        for word in TOKEN.findall(text.lower()):
            for language, words in WORDS.items():
                if word in words:
                    votes[language] += 1
    if not votes:
        return default
    language, count = votes.most_common(1)[0]
    if language != default and count < 2 * votes[default]:
        return default
    return language
