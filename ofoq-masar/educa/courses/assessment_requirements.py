"""Student-specific prerequisites; publication and content progress remain separate."""
from .models import Assessment, AssessmentAttempt


def published_tests(course):
    candidates = Assessment.objects.filter(course=course, status='published',
        published_version__course_revision_id=course.published_revision_id,
        published_version__course_revision__status='approved').select_related('published_version__module__source')
    return [test for test in candidates if test.is_available and (
        test.published_version.module is None or (
            test.published_version.module.source_id is not None and
            test.published_version.module.source.course_id == course.pk))]


def unlock_states(student, course, tests, *, attempts=None):
    """Compute all gates together, using exactly the player's published syllabus.

    A submitted unit-test attempt qualifies regardless of pass/fail or version.
    Old results stay attached to the stable assessment identity. Empty scopes have
    no content prerequisite; missing/broken Content items never count as lessons.
    Callers must first verify authentication and enrollment.
    """
    if not tests:
        return {}
    from .details import syllabus
    from students.models import ContentCompletion

    modules, _, _ = syllabus(course)
    by_module = {module.pk: {content.pk for content in module.lesson_rows} for module in modules}
    all_contents = set().union(*by_module.values()) if by_module else set()
    completed = set(ContentCompletion.objects.filter(student=student, content_id__in=all_contents)
                    .values_list('content_id', flat=True))
    if attempts is None:
        attempts = AssessmentAttempt.objects.filter(student=student, assessment_id__in=[test.pk for test in tests])
    submitted = {attempt.assessment_id for attempt in attempts if attempt.status == 'submitted'}
    unit_tests = {test.pk for test in tests if test.published_version.module_id is not None}
    result = {}
    for test in tests:
        module = test.published_version.module
        required_contents = by_module.get(module.source_id, set()) if module else all_contents
        missing_contents = len(required_contents - completed)
        missing_tests = len(unit_tests - submitted) if module is None else 0
        messages = []
        if missing_contents:
            messages.append(f'أكمل محتويات {"الوحدة" if module else "الدورة"} أولًا، متبقٍ {missing_contents}')
        if missing_tests:
            messages.append(f'سلّم محاولة في كل اختبار وحدة، متبقٍ {missing_tests} (النجاح غير مطلوب)')
        result[test.pk] = {'is_unlocked': not (missing_contents or missing_tests),
            'remaining_content_count': missing_contents, 'remaining_unit_test_count': missing_tests,
            'unlock_message': '؛ '.join(messages)}
    return result
