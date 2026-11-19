"""Data-copy foundation for course review; deliberately no publication/attempt API."""
from .assessment_models import AssessmentVersion, AssessmentQuestion, AssessmentOption


def publish_assessment_versions(revision):
    """Caller owns Course lock; course/revision approval and this switch are atomic."""
    from .assessment_models import Assessment
    from django.utils import timezone
    versions = list(revision.assessment_versions.select_related('assessment'))
    for version in versions:
        version.validate_ready()
    # Omission from the approved snapshot withdraws the test, never its history.
    Assessment.objects.filter(course_id=revision.course_id).exclude(
        pk__in=[version.assessment_id for version in versions],
    ).update(status='draft', published_version=None, updated_at=timezone.now())
    for version in versions:
        assessment = version.assessment
        assessment.published_version = version
        assessment.status = 'published'
        assessment.save(update_fields=['published_version', 'status', 'updated_at'])


def clone_assessment_versions(source, target, module_map):
    """Called in the existing locked transaction for course editing/restoration."""
    for version in source.assessment_versions.prefetch_related('questions__options'):
        draft = AssessmentVersion.objects.create(
            assessment=version.assessment, course_revision=target,
            module=module_map[version.module_id] if version.module_id else None,
            title=version.title, instructions=version.instructions,
            pass_percentage=version.pass_percentage, max_attempts=version.max_attempts,
        )
        for question in version.questions.all():
            copied = AssessmentQuestion.objects.create(version=draft, text=question.text,
                order=question.order, points=question.points)
            for option in question.options.all():
                AssessmentOption.objects.create(question=copied, text=option.text,
                    order=option.order, is_correct=option.is_correct)
