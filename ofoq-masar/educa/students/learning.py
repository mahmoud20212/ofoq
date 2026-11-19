"""Student operations on canonical Content IDs, never revision or item IDs."""

from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from courses.details import syllabus
from courses.models import Course
from .models import ContentCompletion, CourseResume


_read_snapshot = ContextVar('student_learning_read_snapshot', default=None)


def _snapshot_for(student):
    snapshot = _read_snapshot.get()
    return snapshot if snapshot and snapshot['student_id'] == student.pk else None


@contextmanager
def learning_read_snapshot(student, *, course_ids=None):
    """Share an authorized, read-only batch during one view's context building.

    No data is persisted. Writes bypass and invalidate this scoped snapshot;
    following requests always perform fresh access checks.
    """
    _require_student(student)
    from .views import joined_courses

    courses = joined_courses(student)
    if course_ids is not None:
        courses = courses.filter(pk__in=course_ids)
    courses = list(courses.prefetch_related('modules__contents__item', 'modules__contents__content_type'))
    by_id = {course.pk: course for course in courses}
    contents = {}
    for course in courses:
        modules, _, _ = syllabus(course)
        contents[course.pk] = [content for module in modules for content in module.lesson_rows]
    resumes = {row.course_id: row for row in CourseResume.objects.filter(student=student, course_id__in=by_id)} if by_id else {}
    token = _read_snapshot.set({'student_id': student.pk, 'courses': by_id, 'contents': contents, 'resumes': resumes, 'progress': None})
    try:
        yield courses
    finally:
        _read_snapshot.reset(token)


def _require_student(student):
    if not student.is_authenticated or not student.is_active:
        raise PermissionDenied


def _learning_context(student, course_id, *, lock=False):
    _require_student(student)
    snapshot = _snapshot_for(student)
    if snapshot and not lock:
        course = snapshot['courses'].get(course_id)
        if course is None:
            raise Http404('الدورة غير متاحة لك')
        return course, snapshot['contents'][course_id]
    if lock:
        _read_snapshot.set(None)
    # Import at call time to share the player access policy without a module cycle.
    from .views import joined_courses

    if lock:
        # Publication also locks Course: keep validation and writes on one syllabus.
        get_object_or_404(Course.objects.select_for_update(), pk=course_id)
    course = get_object_or_404(joined_courses(student), pk=course_id)
    modules, _, _ = syllabus(course)
    return course, [content for module in modules for content in module.lesson_rows]


def _selected_content(contents, content_id):
    content = next((item for item in contents if item.pk == content_id), None)
    if content is None:
        raise Http404('المحتوى غير متاح لك')
    return content


@transaction.atomic
def mark_content_complete(student, course_id, content_id):
    _, contents = _learning_context(student, course_id, lock=True)
    content = _selected_content(contents, content_id)
    ContentCompletion.objects.get_or_create(student=student, content=content)
    return ContentCompletion.objects.filter(student=student, content=content).exists()


@transaction.atomic
def clear_content_completion(student, course_id, content_id):
    _, contents = _learning_context(student, course_id, lock=True)
    content = _selected_content(contents, content_id)
    ContentCompletion.objects.filter(student=student, content=content).delete()
    return ContentCompletion.objects.filter(student=student, content=content).exists()


@transaction.atomic
def record_content_visit(student, course_id, content_id):
    course, contents = _learning_context(student, course_id, lock=True)
    content = _selected_content(contents, content_id)
    resume, _ = CourseResume.objects.update_or_create(
        student=student, course=course,
        defaults={'last_content': content, 'last_visited_at': timezone.now()},
    )
    return resume


def resume_content(student, course_id):
    """Resolve a destination without recording a visit or changing saved state."""
    course, contents = _learning_context(student, course_id)
    snapshot = _snapshot_for(student)
    if snapshot:
        saved = snapshot['resumes'].get(course.pk)
        saved_id = saved.last_content_id if saved else None
    else:
        saved_id = CourseResume.objects.filter(student=student, course=course).values_list('last_content_id', flat=True).first()
    return next((content for content in contents if content.pk == saved_id), contents[0] if contents else None)


def student_courses_progress(student, *, course_ids=None):
    """Batch progress keyed by accessible course ID; query count is not per course.

    All items returned by the player's syllabus are required and weighted equally.
    A saved visit (including a cleared destination) or a recorded completion means
    learning has started. Only currently available completions count numerically.
    """
    _require_student(student)
    from .views import joined_courses

    snapshot = _snapshot_for(student)
    if snapshot and snapshot['progress'] is not None:
        return {pk: row for pk, row in snapshot['progress'].items() if course_ids is None or pk in course_ids}
    if snapshot:
        courses = list(snapshot['courses'].values())
    else:
        courses = joined_courses(student)
        if course_ids is not None:
            courses = courses.filter(pk__in=course_ids)
        courses = list(courses.prefetch_related('modules__contents__item', 'modules__contents__content_type'))
    if not courses:
        return {}

    available = {}
    for course in courses:
        modules, _, _ = syllabus(course)
        available[course.pk] = {content.pk for module in modules for content in module.lesson_rows}

    completed = {course.pk: set() for course in courses}
    started = set(snapshot['resumes']) if snapshot else set(CourseResume.objects.filter(student=student, course_id__in=available).values_list('course_id', flat=True))
    rows = ContentCompletion.objects.filter(
        student=student, content__module__course_id__in=available,
    ).values_list('content__module__course_id', 'content_id')
    for course_id, content_id in rows:
        started.add(course_id)
        if content_id in available[course_id]:
            completed[course_id].add(content_id)

    progress = {}
    for course_id, content_ids in available.items():
        total, count = len(content_ids), len(completed[course_id])
        progress[course_id] = {
            'available_content_count': total,
            'completed_content_count': count,
            # Integer floor prevents a partially completed course displaying 100%.
            'completion_percentage': count * 100 // total if total else 0,
            'has_started': course_id in started,
            'is_content_complete': total > 0 and count == total,
        }
    if snapshot:
        snapshot['progress'] = progress
        return {pk: row for pk, row in progress.items() if course_ids is None or pk in course_ids}
    return progress


def course_progress(student, course_id):
    progress = student_courses_progress(student, course_ids=[course_id])
    if course_id not in progress:
        raise Http404('الدورة غير متاحة لك')
    return progress[course_id]


def student_progress_summary(student):
    """Content completion only: this does not imply exam success or certification."""
    courses = student_courses_progress(student)
    completed = sum(row['is_content_complete'] for row in courses.values())
    return {
        'enrolled_course_count': len(courses),
        'content_complete_course_count': completed,
        'content_incomplete_course_count': len(courses) - completed,
        'started_incomplete_course_count': sum(
            row['has_started'] and not row['is_content_complete'] for row in courses.values()
        ),
        'completed_available_content_count': sum(row['completed_content_count'] for row in courses.values()),
        'available_content_count': sum(row['available_content_count'] for row in courses.values()),
    }
