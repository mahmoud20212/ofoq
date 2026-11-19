"""Student HTML adapters for the existing assessment operations, including no-JS."""
from copy import deepcopy
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.utils.dateparse import parse_datetime

from courses import assessment_services as services
from .views import StudentCourseOverviewView


def _login_url(target):
    return reverse('sso_login') + '?' + urlencode({'next': target})


def _url(name, course_id, assessment_id, attempt_id=None):
    kwargs = {'course_id': course_id, 'assessment_id': assessment_id}
    if attempt_id is not None:
        kwargs['attempt_id'] = attempt_id
    return reverse('student_assessment_' + name, kwargs=kwargs)


def student_page(view):
    @never_cache
    @csrf_protect
    @wraps(view)
    def protected(request, *args, **kwargs):
        if not request.user.is_authenticated:
            if request.method == 'GET':
                return redirect(_login_url(request.get_full_path()))
            return render(request, 'students/assessments/session.html',
                {'login_url': _login_url(request.path), 'page_title': 'انتهت الجلسة', 'breadcrumbs': []}, status=401)
        try:
            return view(request, *args, **kwargs)
        except services.AssessmentConflict as exc:
            if exc.code != 'prerequisites_not_met':
                raise
            messages.warning(request, exc.detail)
            return redirect(_url('page', kwargs['course_id'], kwargs['assessment_id']))
    return protected


def _context(request, course_id, assessment_id):
    base = StudentCourseOverviewView()
    base.setup(request, course_id=course_id)
    context = base.get_context_data()
    selected = next((row for row in context['all_assessment_rows'] if row['id'] == assessment_id), None)
    context.update(assessment_page=True, learning_mode=True, hide_course_sidebar=True,
        current_assessment_id=assessment_id, selected_module=next((module for module in context['modules']
            if selected and module.pk == selected['module_id']), None),
        assessment_url=_url('page', course_id, assessment_id), history_url=_url('history_page', course_id, assessment_id))
    context['history_can_resume'] = bool(selected and selected['is_unlocked'])
    context['breadcrumbs'][-1]['url'] = reverse('student_course_overview', args=[course_id])
    module = context['selected_module']
    if module is not None:
        context['breadcrumbs'].append({'label': 'الوحدات', 'url': reverse('student_course_units', args=[course_id])})
        context['breadcrumbs'].append({'label': module.title, 'url': reverse('student_module', args=[course_id, module.pk])})
    return context


def _history(request, course_id, assessment_id, page=1):
    data = services.attempt_history(request.user, course_id, assessment_id, page=page)
    for row in data['attempts']:
        row['date'] = parse_datetime(row['started_at'])
    return data


def _assessment_navigation(context, assessment_id):
    """Follow the already-authorized curriculum: contents, unit tests, course tests."""
    course_id = context['course'].pk
    sequence = []
    for module in context['modules']:
        for content in module.lesson_rows:
            sequence.append({'kind': 'content', 'id': content.pk, 'title': content.item.title,
                'url': reverse('student_lesson', args=[course_id, content.pk])})
        for test in module.assessment_rows:
            sequence.append({'kind': 'assessment', 'id': test['id'], 'title': test['title'],
                'url': _url('page', course_id, test['id'])})
    for test in context['course_assessment_rows']:
        sequence.append({'kind': 'assessment', 'id': test['id'], 'title': test['title'],
            'url': _url('page', course_id, test['id'])})
    index = next((i for i, row in enumerate(sequence)
                  if row['kind'] == 'assessment' and row['id'] == assessment_id), None)
    return {'previous_curriculum_item': sequence[index - 1] if index is not None and index > 0 else None,
            'next_curriculum_item': sequence[index + 1] if index is not None and index + 1 < len(sequence) else None}


def _decorate_attempt(request, course_id, assessment_id, data, *, posted=False):
    """Copy only safe presentation data; preserve unsaved inputs on validation failure."""
    confirmed = [{'question_key': row['question_key'], 'option_key': row['selected_option_key']} for row in data['questions']]
    visible = deepcopy(data)
    if posted:
        for row in visible['questions']:
            values = request.POST.getlist('answer_' + row['question_key'])
            if len(values) == 1 and values[0] in {'', *(option['option_key'] for option in row['options'])}:
                row['selected_option_key'] = values[0]
    answered = sum(bool(row['selected_option_key']) for row in visible['questions'])
    return {'attempt_data': visible, 'confirmed_answers': confirmed, 'answered_count': answered,
        'unanswered_count': len(data['questions']) - answered, 'initial_unsaved': posted,
        'save_url': _url('answers', course_id, assessment_id, data['attempt_id']),
        'submit_url': _url('submit', course_id, assessment_id, data['attempt_id']),
        'read_url': _url('attempt', course_id, assessment_id, data['attempt_id']),
        'result_url': _url('result_page', course_id, assessment_id, data['attempt_id']),
        'login_url': _login_url(request.path)}


def _form_answers(request, data):
    known = {'answer_' + row['question_key'] for row in data['questions']}
    allowed = known | {'csrfmiddlewaretoken', 'action', 'confirm_submit'}
    if set(request.POST) - allowed:
        raise ValidationError('الطلب يتضمن حقولًا غير مسموحة')
    rows = []
    for question in data['questions']:
        values = request.POST.getlist('answer_' + question['question_key'])
        if len(values) > 1:
            raise ValidationError('لا يمكن اختيار أكثر من إجابة للسؤال نفسه')
        rows.append({'question_key': question['question_key'], 'option_key': values[0] if values else ''})
    return rows


@student_page
@require_GET
def introduction(request, course_id, assessment_id):
    test = services.assessment_presentation(request.user, course_id, assessment_id)
    context = _context(request, course_id, assessment_id)
    if not any(row['id'] == assessment_id for row in context['all_assessment_rows']):
        raise Http404
    context.update(test=test, page_title=test['title'], history=_history(request, course_id, assessment_id))
    context.update(_assessment_navigation(context, assessment_id))
    context['breadcrumbs'].append({'label': test['title'], 'url': None})
    return render(request, 'students/assessments/introduction.html', context)


@student_page
@require_POST
def begin(request, course_id, assessment_id):
    try:
        data, _ = services.start_attempt(request.user, course_id, assessment_id)
    except services.AssessmentConflict as exc:
        messages.error(request, exc.detail)
        return redirect(_url('page', course_id, assessment_id))
    return redirect(_url('solve', course_id, assessment_id, data['attempt_id']))


@student_page
@require_http_methods(['GET', 'POST'])
def solve(request, course_id, assessment_id, attempt_id):
    data = services.attempt_presentation(request.user, course_id, assessment_id, attempt_id)
    if data['status'] == 'submitted':
        return redirect(_url('result_page', course_id, assessment_id, attempt_id))
    context = _context(request, course_id, assessment_id)
    if not context['history_can_resume']:
        raise Http404
    context.update(page_title=data['title'], test={'title': data['title']}, assessment_solving=True,
        **_decorate_attempt(request, course_id, assessment_id, data, posted=request.method == 'POST'))
    context['breadcrumbs'].append({'label': data['title'], 'url': context['assessment_url']})
    context['breadcrumbs'].append({'label': f"المحاولة {data['number']}", 'url': None})
    status = 200
    if request.method == 'POST':
        try:
            rows = _form_answers(request, data)
            action = request.POST.get('action')
            if action == 'save':
                services.save_answers(request.user, course_id, assessment_id, attempt_id, rows)
                messages.success(request, 'تم حفظ إجابات الاختبار')
                return redirect(request.path)
            if action == 'confirm_submit':
                context.update(services.submission_preview(request.user, course_id, assessment_id, attempt_id, rows), confirm_submission=True)
            elif action == 'submit' and request.POST.get('confirm_submit') == 'yes':
                services.submit_attempt(request.user, course_id, assessment_id, attempt_id, rows)
                return redirect(_url('result_page', course_id, assessment_id, attempt_id))
            elif action != 'edit':
                raise ValidationError('أكّد تسليم المحاولة قبل إرسالها')
            else:
                services.submission_preview(request.user, course_id, assessment_id, attempt_id, rows)
        except ValidationError as exc:
            context['form_error'], status = '؛ '.join(exc.messages), 400
        except services.AssessmentConflict as exc:
            if exc.code == 'attempt_submitted':
                return redirect(_url('result_page', course_id, assessment_id, attempt_id))
            context['form_error'], status = exc.detail, 409
    return render(request, 'students/assessments/solve.html', context, status=status)


@student_page
@require_GET
def result_page(request, course_id, assessment_id, attempt_id):
    try:
        data = services.read_attempt(request.user, course_id, assessment_id, attempt_id, result_only=True)
    except services.AssessmentConflict:
        return redirect(_url('solve', course_id, assessment_id, attempt_id))
    context = _context(request, course_id, assessment_id)
    history = _history(request, course_id, assessment_id)
    # Re-entry must use a valid current publication; historical results remain readable.
    try:
        current = services.assessment_presentation(request.user, course_id, assessment_id)
    except Http404:
        current = None
    context.update(attempt_data=data, page_title='نتيجة الاختبار', test={'title': data['title']}, history=history,
        current_test=current, start_url=_url('begin', course_id, assessment_id))
    context['breadcrumbs'].append({'label': data['title'], 'url': context['assessment_url'] if current else None})
    context['breadcrumbs'].append({'label': 'النتيجة', 'url': None})
    return render(request, 'students/assessments/result.html', context)


@student_page
@require_GET
def history_page(request, course_id, assessment_id):
    history = _history(request, course_id, assessment_id, page=request.GET.get('page', 1))
    context = _context(request, course_id, assessment_id)
    context.update(history=history, page_title='سجل محاولات الاختبار')
    context['breadcrumbs'].append({'label': 'سجل المحاولات', 'url': None})
    return render(request, 'students/assessments/history.html', context)
