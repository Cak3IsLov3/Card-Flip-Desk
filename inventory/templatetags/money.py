from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def euro(value):
    """Toont een Decimal als '€ 1.234,50'; None wordt '–'."""
    if value is None or value == "":
        return "–"
    value = Decimal(value).quantize(Decimal("0.01"))
    sign = "-" if value < 0 else ""
    whole, cents = f"{abs(value):.2f}".split(".")
    whole = f"{int(whole):,}".replace(",", ".")
    return f"{sign}€ {whole},{cents}"


@register.filter
def pct(value):
    if value is None:
        return "–"
    return f"{value}%".replace(".", ",")
