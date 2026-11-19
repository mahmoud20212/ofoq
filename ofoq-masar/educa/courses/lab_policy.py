"""Deployment policy, bounded by the schema's reviewed absolute ceilings."""
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError

ABSOLUTE_CPU_SECONDS = Decimal('10.00')
ABSOLUTE_MEMORY_KB = 524288
ABSOLUTE_OUTPUT_BYTES = 1048576
DEFAULTS = {'cpu_seconds': '2.00', 'max_cpu_seconds': '10.00',
            'memory_kb': 262144, 'max_memory_kb': 524288,
            'output_bytes': 65536, 'max_output_bytes': 1048576}


def resource_limits():
    configured = getattr(settings, 'LAB_RESOURCE_LIMITS', {})
    if not isinstance(configured, dict) or set(configured) - set(DEFAULTS):
        raise ImproperlyConfigured('Invalid LAB_RESOURCE_LIMITS configuration')
    values = {**DEFAULTS, **configured}
    try:
        for key in ('cpu_seconds', 'max_cpu_seconds'):
            value = Decimal(str(values[key]))
            if not value.is_finite() or value != value.quantize(Decimal('.01')):
                raise ValueError
            values[key] = value
        for key in ('memory_kb', 'max_memory_kb', 'output_bytes', 'max_output_bytes'):
            if type(values[key]) is not int:
                raise ValueError
        for key, cap in [('cpu_seconds', ABSOLUTE_CPU_SECONDS), ('memory_kb', ABSOLUTE_MEMORY_KB), ('output_bytes', ABSOLUTE_OUTPUT_BYTES)]:
            if not 0 < values[key] <= values['max_' + key] <= cap:
                raise ValueError
    except (ValueError, TypeError, InvalidOperation):
        raise ImproperlyConfigured('Lab defaults and limits must be positive and within schema ceilings')
    return values


def default_cpu_seconds():
    return resource_limits()['cpu_seconds']


def default_memory_kb():
    return resource_limits()['memory_kb']


def default_output_bytes():
    return resource_limits()['output_bytes']


def validate_resource_limits(version):
    limits = resource_limits()
    for field in ('cpu_seconds', 'memory_kb', 'output_bytes'):
        try:
            value = getattr(version, field)
            if field == 'cpu_seconds':
                value = Decimal(str(value))
                if not value.is_finite():
                    raise ValueError
            elif type(value) is not int:
                raise ValueError
            valid = 0 < value <= limits['max_' + field]
        except (ValueError, TypeError, InvalidOperation):
            valid = False
        if not valid:
            raise ValidationError('Challenge resources exceed the current platform limits')
