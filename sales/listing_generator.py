"""Titels en beschrijvingen voor listings, opgebouwd uit kaartgegevens.

Patronen gebruiken plaatshouders zoals `{jaar} {set} {speler} #{nummer}`.
Lege velden verdwijnen netjes: een losse `#` of `()` blijft niet achter.
De uitkomst is platte tekst; escapen gebeurt bij het tonen in HTML.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from inventory.models import Card, PhotoLabel, Variant
from inventory.photos import photo_checklist

TITLE_MAX_LENGTH = 80  # eBay-limiet, in tekens

DEFAULT_TITLE_PATTERN = "{jaar} {set} {speler} #{nummer} {variant} {conditie}"
DEFAULT_DESCRIPTION_PATTERN = (
    "{jaar} {set} – {speler} #{nummer}\n"
    "Variant: {variant}\n"
    "Conditie: {conditie}\n"
    "\n"
    "{opmerkingen}\n"
    "{defecten}\n"
    "\n"
    "Verzending in een toploader en een stevige envelop. "
    "Bekijk de foto's: je ontvangt precies deze kaart."
)

PLACEHOLDERS = {
    "jaar": "Jaar",
    "set": "Set",
    "speler": "Speler",
    "nummer": "Kaartnummer",
    "variant": "Variant (leeg bij base)",
    "conditie": "Conditie",
    "sport": "Sport",
    "opmerkingen": "Notities bij de kaart",
    "defecten": "Melding als er foto's van defecten zijn",
}
_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
# Een "woord" dat na het invullen alleen nog leestekens bevat, hoort er niet meer bij.
_ORPHAN_RE = re.compile(r"^[#\-–—|/•·,:;()\[\]]+$")
_EMPTY_LABEL_RE = re.compile(r"^[^:\n]{1,40}:$")


class PatternError(ValueError):
    pass


def unknown_placeholders(pattern: str) -> list[str]:
    return sorted({p for p in _PLACEHOLDER_RE.findall(pattern) if p not in PLACEHOLDERS})


def card_values(card: Card, photos=None) -> dict[str, str]:
    photos = list(card.photos.all()) if photos is None else photos
    defects = sum(1 for p in photos if p.label == PhotoLabel.DEFECT)
    defect_note = ""
    if defects:
        noun = "foto" if defects == 1 else "foto's"
        defect_note = f"Let op: {defects} {noun} van defecten bijgevoegd."
    return {
        "jaar": str(card.year or ""),
        "set": card.set_name,
        "speler": card.player,
        "nummer": card.card_number,
        "variant": "" if card.variant == Variant.BASE else card.get_variant_display(),
        "conditie": card.condition,
        "sport": card.sport,
        "opmerkingen": card.notes,
        "defecten": defect_note,
    }


def render(pattern: str, values: dict[str, str], *, single_line: bool) -> tuple[str, list[str]]:
    """Vult een patroon in. Geeft de tekst en de lege plaatshouders terug."""
    unknown = unknown_placeholders(pattern)
    if unknown:
        raise PatternError("Onbekende plaatshouder(s): " + ", ".join("{" + u + "}" for u in unknown))

    empty = []

    def substitute(match):
        key = match.group(1)
        value = clean_text(values.get(key, ""), single_line=single_line)
        if not value:
            empty.append(key)
        return value

    text = _PLACEHOLDER_RE.sub(substitute, pattern)
    if single_line:
        text = _tidy_line(text)
    else:
        lines = [_tidy_line(line) for line in text.splitlines()]
        # "Variant:" zonder waarde is ruis; zo'n regel valt weg.
        lines = [line for line in lines if not _EMPTY_LABEL_RE.match(line)]
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text, sorted(set(empty))


def clean_text(value: str, *, single_line: bool) -> str:
    """Verwijdert stuurtekens en (voor titels) regeleinden; normaliseert Unicode."""
    value = unicodedata.normalize("NFC", value or "")
    allowed = {"\n"} if not single_line else set()
    value = "".join(
        ch if ch in allowed or unicodedata.category(ch)[0] != "C" else " " for ch in value
    )
    return value.strip()


def _tidy_line(line: str) -> str:
    words = [w for w in line.split() if not _ORPHAN_RE.match(w)]
    return " ".join(words)


def truncate_title(title: str, limit: int = TITLE_MAX_LENGTH) -> str:
    """Kapt af op een woordgrens; alleen als dat niet kan, midden in een woord."""
    if len(title) <= limit:
        return title
    cut = title[: limit + 1].rsplit(" ", 1)[0]
    if not cut or len(cut) > limit:
        cut = title[:limit]
    return _tidy_line(cut)


@dataclass
class GeneratedListing:
    title: str
    full_title: str
    description: str
    warnings: list[str] = field(default_factory=list)

    @property
    def was_truncated(self) -> bool:
        return self.title != self.full_title


def generate(card: Card, title_pattern: str, description_pattern: str) -> GeneratedListing:
    photos = list(card.photos.all())
    values = card_values(card, photos)
    full_title, empty_in_title = render(title_pattern, values, single_line=True)
    description, _ = render(description_pattern, values, single_line=False)

    title = truncate_title(full_title)
    warnings = []
    if not full_title:
        warnings.append("De titel is leeg.")
    if title != full_title:
        dropped = full_title[len(title):].strip()
        warnings.append(
            f"Titel is {len(full_title)} tekens (max. {TITLE_MAX_LENGTH}) en is afgekapt; "
            f"weggevallen: “{dropped}”."
        )
    labels = {k: PLACEHOLDERS[k] for k in empty_in_title if k not in ("variant", "defecten", "opmerkingen")}
    if labels:
        warnings.append("Leeg in de titel: " + ", ".join(labels.values()).lower() + ".")
    warnings.extend(photo_checklist(card, photos))
    return GeneratedListing(title=title, full_title=full_title, description=description, warnings=warnings)
