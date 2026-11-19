from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


NO_EXPERIENCE = 'لا تحتاج خبرة سابقة'
REQUIRED_DETAILS = {
    'title': 'عنوان الدورة',
    'subject': 'مجال التعلّم',
    'cover': 'غلاف الدورة',
    'short_description': 'الوصف المختصر',
    'overview': 'الوصف الكامل',
    'learning_outcomes': 'أهداف التعلّم',
    'requirements': 'المتطلبات',
    'target_audience': 'الفئة المستهدفة',
}


def details_errors(values):
    """Shared requirements for saved metadata, step access and publication."""
    errors = {}
    for name, label in REQUIRED_DETAILS.items():
        value = values.get(name)
        if not value or (isinstance(value, str) and not value.strip()):
            errors[name] = f'أكمل {label}'
    cover = values.get('cover')
    if cover and hasattr(cover, 'storage') and not cover.storage.exists(cover.name):
        errors['cover'] = 'أعد رفع غلاف الدورة؛ الملف الحالي غير موجود'
    if values.get('is_paid'):
        price = values.get('price')
        try:
            price = Decimal(price)
            valid = price.is_finite() and price >= Decimal('0.01') and price == price.quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError, ValueError):
            valid = False
        if not valid:
            errors['price'] = 'أدخل سعرًا موجبًا بدقتين عشريتين للدورة المدفوعة'
    return errors


def validate_details(revision):
    errors = details_errors({name: getattr(revision, name) for name in [*REQUIRED_DETAILS, 'is_paid', 'price']})
    if errors:
        raise ValidationError(errors)
