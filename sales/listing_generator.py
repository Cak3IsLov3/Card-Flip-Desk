"""Listing titles and descriptions built from card data.

Patterns use placeholders such as `{year} {set} {player} #{number}`.
Empty fields disappear cleanly: no stray `#` or `()` is left behind.
The result is plain text; escaping happens when it is shown as HTML.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from inventory.models import Card, PhotoLabel
from inventory.photos import photo_checklist

TITLE_MAX_LENGTH = 80  # eBay limit, in characters

DEFAULT_TITLE_PATTERN = "{year} {set} {player} #{number} {variant} {condition}"
DEFAULT_DESCRIPTION_PATTERN = (
    "{year} {set} – {player} #{number}\n"
    "Variant: {variant}\n"
    "Condition: {condition}\n"
    "\n"
    "{notes}\n"
    "{defects}\n"
    "\n"
    "Shipped in a toploader inside a sturdy envelope. "
    "Check the photos: you receive exactly this card."
)

PLACEHOLDERS = {
    "year": "Year",
    "set": "Set",
    "player": "Player",
    "number": "Card number",
    "variant": "Variants, e.g. Rookie Gold Refractor (empty for base)",
    "parallel": "Which parallel (empty if none)",
    "serial": "Serial number of a numbered parallel, e.g. 23/50",
    "insert": "Which insert (empty if none)",
    "condition": "Condition",
    "sport": "Sport",
    "notes": "Notes on the card",
    "defects": "A note when there are photos of defects",
}
_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
# A "word" that is only punctuation after filling in no longer belongs there.
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
        noun = "photo" if defects == 1 else "photos"
        defect_note = f"Note: {defects} {noun} of defects included."
    return {
        "year": str(card.year or ""),
        "set": card.set_name,
        "player": card.player,
        "number": card.card_number,
        "variant": " ".join(card.variant_labels),
        "parallel": card.parallel_name if "parallel" in card.variants else "",
        "serial": card.parallel_serial if "parallel" in card.variants else "",
        "insert": card.insert_name if "insert" in card.variants else "",
        "condition": card.get_condition_display(),
        "sport": card.sport,
        "notes": card.notes,
        "defects": defect_note,
    }


def render(pattern: str, values: dict[str, str], *, single_line: bool) -> tuple[str, list[str]]:
    """Fill in a pattern. Returns the text and the placeholders that were empty."""
    unknown = unknown_placeholders(pattern)
    if unknown:
        raise PatternError("Unknown placeholder(s): " + ", ".join("{" + u + "}" for u in unknown))

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
        # "Variant:" without a value is noise; such a line is dropped.
        lines = [line for line in lines if not _EMPTY_LABEL_RE.match(line)]
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text, sorted(set(empty))


def clean_text(value: str, *, single_line: bool) -> str:
    """Remove control characters and (for titles) line breaks; normalise Unicode."""
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
    """Cut at a word boundary; only mid-word when there is no other option."""
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
        warnings.append("The title is empty.")
    if title != full_title:
        dropped = full_title[len(title):].strip()
        warnings.append(
            f"Title is {len(full_title)} characters (max. {TITLE_MAX_LENGTH}) and was cut; "
            f"dropped: “{dropped}”."
        )
    optional = ("variant", "parallel", "serial", "insert", "defects", "notes")
    labels = {k: PLACEHOLDERS[k] for k in empty_in_title if k not in optional}
    if labels:
        warnings.append("Empty in the title: " + ", ".join(labels.values()).lower() + ".")
    warnings.extend(photo_checklist(card, photos))
    return GeneratedListing(title=title, full_title=full_title, description=description, warnings=warnings)
