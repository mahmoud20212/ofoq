from django import template
from decimal import Decimal, InvalidOperation

register = template.Library()


@register.filter
def compact_number(value):
    """Display server numbers without trailing zeros or additional rounding."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return value if value is not None else ''
    if not number.is_finite():
        return value
    if number == 0:
        return '0'
    text = format(number, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


@register.filter
def model_name(obj):
    try:
        return obj._meta.model_name
    except AttributeError:
        return None
