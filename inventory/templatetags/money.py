from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def euro(value):
    """Show a Decimal as '€1,234.50' (negative: '-€1.50'); None becomes '–'."""
    if value is None or value == "":
        return "–"
    value = Decimal(value).quantize(Decimal("0.01"))
    sign = "-" if value < 0 else ""
    return f"{sign}€{abs(value):,.2f}"


@register.filter
def pct(value):
    if value is None:
        return "–"
    return f"{value}%"
