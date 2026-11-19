from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.signals import user_logged_in
from django.db import transaction
from django.dispatch import receiver
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .models import CartItem, Course

SESSION_KEY = 'masar_cart'


def price_for(course):
    """Fail closed until real paid-course data is introduced in its own phase."""
    if not getattr(course, 'is_paid', False):
        return None
    if not getattr(course, 'pricing_configured', True):
        return None
    try:
        price = Decimal(str(course.price))
    except (AttributeError, InvalidOperation, TypeError, ValueError):
        return None
    if not price.is_finite() or price <= 0:
        return None
    if getattr(course, 'status', 'published') != 'published':
        return None
    return price.quantize(Decimal('0.01'))


def session_ids(request):
    raw = request.session.get(SESSION_KEY, [])
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(x for x in raw if type(x) is int and x > 0))[:100]


def cart_rows(request):
    signed_in = request.user.is_authenticated
    ids = list(CartItem.objects.filter(user=request.user).values_list('course_id', flat=True)) if signed_in else session_ids(request)
    courses = {c.pk: c for c in Course.objects.filter(pk__in=ids).select_related('subject', 'owner')}
    owned = set(request.user.courses_joined.filter(pk__in=ids).values_list('pk', flat=True)) if signed_in else set()
    rows, valid = [], []
    for pk in ids:
        course = courses.get(pk)
        price = price_for(course) if course else None
        if price is not None and pk not in owned:
            rows.append({'course': course, 'price': price})
            valid.append(pk)
    if signed_in:
        CartItem.objects.filter(user=request.user).exclude(course_id__in=valid).delete()
    elif ids != valid:
        request.session[SESSION_KEY] = valid
    return rows, len(ids) - len(valid)


def navigation_context(request):
    count = CartItem.objects.filter(user=request.user).count() if request.user.is_authenticated else len(session_ids(request))
    return {'cart_count': count, 'account_center_url': getattr(settings, 'OFOQ_ACCOUNT_CENTER_URL', ''), 'social_links': getattr(settings, 'OFOQ_SOCIAL_LINKS', {})}


def cart_detail(request):
    rows, removed = cart_rows(request)
    if removed:
        messages.info(request, 'تم استبعاد دورات غير متاحة للشراء أو ملتحق بها من السلة.')
    return render(request, 'courses/cart.html', {'cart_rows': rows, 'cart_count': len(rows), 'cart_total': sum((r['price'] for r in rows), Decimal('0.00'))})


@require_POST
def cart_add(request, course_id):
    course = Course.objects.filter(pk=course_id).first()
    if course is None or price_for(course) is None:
        messages.info(request, 'هذه الدورة غير متاحة للإضافة إلى سلة المشتريات حاليًا.')
    elif request.user.is_authenticated:
        if course.students.filter(pk=request.user.pk).exists():
            messages.info(request, 'أنت ملتحق بهذه الدورة بالفعل.')
        else:
            CartItem.objects.get_or_create(user=request.user, course=course)
    else:
        ids = session_ids(request)
        if course.pk not in ids and len(ids) < 100:
            ids.append(course.pk)
        request.session[SESSION_KEY] = ids
        request.session.set_expiry(30 * 24 * 60 * 60)
    return redirect('cart_detail')


@require_POST
def cart_remove(request, course_id):
    if request.user.is_authenticated:
        CartItem.objects.filter(user=request.user, course_id=course_id).delete()
    else:
        request.session[SESSION_KEY] = [pk for pk in session_ids(request) if pk != course_id]
    return redirect('cart_detail')


@receiver(user_logged_in, dispatch_uid='masar.merge_guest_cart')
def merge_guest_cart(sender, request, user, **kwargs):
    ids = session_ids(request)
    if not ids:
        return
    with transaction.atomic():
        for course in Course.objects.filter(pk__in=ids):
            if price_for(course) is not None and not course.students.filter(pk=user.pk).exists():
                CartItem.objects.get_or_create(user=user, course=course)
    request.session.pop(SESSION_KEY, None)
