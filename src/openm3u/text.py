import re
import unicodedata

_BRANDING = re.compile(r"^(pluto tv|samsung tv plus|plex|tubi|roku|xumo|stirr)\s+", re.I)
_NOISE = re.compile(r"\b(hd|fhd|uhd|4k)\b", re.I)


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("&", " and ").replace("+", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def channel_key(name: str) -> str:
    """Identity for deduplication. Keeps service branding, since "Pluto TV Comedy"
    and "Plex Comedy" are different channels that happen to share a genre."""
    return fold(_NOISE.sub("", name))


def unbranded(name: str) -> str:
    return fold(_BRANDING.sub("", name.strip()))


def slugify(name: str) -> str:
    return fold(name).replace(" ", "-") or "channel"
