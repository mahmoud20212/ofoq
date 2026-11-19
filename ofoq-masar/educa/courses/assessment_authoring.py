"""Private authoring of reviewed assessment snapshots, never canonical publication."""
import json
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import F, Max
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView
from django.http import Http404, JsonResponse

from .models import Course, CourseRevision
from .assessment_models import Assessment, AssessmentVersion, AssessmentQuestion
from .assessment_forms import AssessmentSettingsForm, AssessmentQuestionForm, OptionFormSet
from .instructor_views import TeacherView
from .instructor_services import is_teacher


def readiness(version):
    try:
        version.validate_ready()
    except ValidationError as exc:
        return exc.messages
    return []


def touch(revision):
    CourseRevision.objects.filter(pk=revision.pk).update(updated=timezone.now())


class AssessmentTeacherView(TeacherView):
    requires_details = True
    section = 'courses'
    page_title = 'اختبارات الدورة'

    def dispatch(self, request, *args, **kwargs):
        if request.method == 'POST' and request.user.is_authenticated:
            # Same Course lock/order as publication. SQLite reserves a writer first.
            with transaction.atomic():
                courses = Course.objects.filter(revisions__pk=kwargs['revision_id'])
                if connection.vendor == 'sqlite':
                    courses.update(status=F('status'))
                else:
                    list(courses.select_for_update())
                response = super().dispatch(request, *args, **kwargs)
        else:
            response = super().dispatch(request, *args, **kwargs)
        if request.headers.get('X-Assessment-Workspace') == '1' and response.status_code in (301, 302):
            return JsonResponse({'workspace_url': response['Location']})
        return response

    def version(self, revision, version_id):
        return get_object_or_404(AssessmentVersion.objects.select_related('module', 'assessment'),
            pk=version_id, course_revision=revision, assessment__course_id=revision.course_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        revision = context['revision']
        context.update(assessment_workspace=True, setup_step='curriculum',
            can_edit=revision.status in ('draft', 'rejected'),
            breadcrumbs=[{'label': revision.title, 'url': reverse('instructor:revision', args=[revision.pk])},
                {'label': 'الاختبارات', 'url': reverse('instructor:assessments', args=[revision.pk])}])
        if self.request.headers.get('X-Assessment-Workspace') == '1':
            context.update(assessment_dialog=True, assessment_layout='instructor/assessments/dialog-layout.html')
        if context.get('version'):
            context['readiness_errors'] = readiness(context['version'])
        return context


class AssessmentListView(AssessmentTeacherView):
    template_name = 'instructor/assessments/list.html'

    def get(self, request, revision_id):
        revision = self.own_revision(revision_id)
        versions = list(revision.assessment_versions.select_related('module').prefetch_related('questions__options'))
        for version in versions:
            version.readiness_errors = readiness(version)
        return self.render_to_response(self.get_context_data(revision=revision, versions=versions, curriculum_tabs_page=True))


class AssessmentSettingsView(AssessmentTeacherView):
    template_name = 'instructor/assessments/settings.html'

    def get_template_names(self):
        if self.request.headers.get('X-Editor-Dialog') == '1':
            return ['instructor/assessments/settings-form.html']
        return super().get_template_names()

    def get(self, request, revision_id, version_id=None):
        revision = self.own_revision(revision_id, editing=True)
        version = self.version(revision, version_id) if version_id else AssessmentVersion(course_revision=revision)
        form = AssessmentSettingsForm(instance=version, revision=revision)
        return self.render_to_response(self.get_context_data(revision=revision, version=version if version.pk else None, form=form))

    def post(self, request, revision_id, version_id=None):
        revision = self.own_revision(revision_id, editing=True)
        version = self.version(revision, version_id) if version_id else AssessmentVersion(course_revision=revision)
        form = AssessmentSettingsForm(request.POST, instance=version, revision=revision)
        # Model validation also needs the assessment/course relationship for a new row.
        if not version_id:
            version.assessment = Assessment(course=revision.course)
        if form.is_valid():
            if not version_id:
                version.assessment.save()
                version.assessment_id = version.assessment.pk
            form.save()
            touch(revision)
            if request.headers.get('X-Editor-Dialog') == '1':
                version.readiness_errors = readiness(version)
                return JsonResponse({'assessment_html': render_to_string(
                    'instructor/assessments/card.html',
                    {'test': version, 'revision': revision, 'can_edit': True}, request=request),
                    'assessment_version_id': version.pk, 'assessment_updated': bool(version_id),
                    'message': 'تم تحديث الاختبار' if version_id else 'تمت إضافة الاختبار إلى نسخة العمل'})
            messages.success(request, 'تم حفظ إعدادات الاختبار في نسخة العمل')
            return redirect('instructor:assessment', revision_id=revision.pk, version_id=version.pk)
        if request.headers.get('X-Editor-Dialog') == '1':
            return JsonResponse({'errors': form.errors.get_json_data()}, status=422)
        # Bound ModelForm values remain intact; readiness uses the persisted row.
        stored = self.version(revision, version_id) if version_id else None
        return self.render_to_response(self.get_context_data(revision=revision, version=stored, form=form))


class AssessmentDetailView(AssessmentTeacherView):
    template_name = 'instructor/assessments/detail.html'

    def get(self, request, revision_id, version_id):
        revision = self.own_revision(revision_id)
        version = self.version(revision, version_id)
        questions = list(version.questions.prefetch_related('options'))
        return self.render_to_response(self.get_context_data(revision=revision, version=version, questions=questions))


class AssessmentQuestionView(AssessmentTeacherView):
    template_name = 'instructor/assessments/question.html'

    def load(self, revision_id, version_id, question_id=None):
        revision = self.own_revision(revision_id, editing=True)
        version = self.version(revision, version_id)
        question = get_object_or_404(AssessmentQuestion, pk=question_id, version=version) if question_id else AssessmentQuestion(
            version=version, order=(version.questions.aggregate(last=Max('order'))['last'] or 0) + 1)
        return revision, version, question

    def get(self, request, revision_id, version_id, question_id=None):
        revision, version, question = self.load(revision_id, version_id, question_id)
        form = AssessmentQuestionForm(instance=question)
        options = OptionFormSet(instance=question, prefix='options')
        # One radio group for the entire question, never per-option checkboxes.
        correct = next((option for option in options.forms if option.instance.is_correct), None)
        return self.render_to_response(self.get_context_data(revision=revision, version=version,
            form=form, options=options, correct_option=correct.prefix if correct else ''))

    def post(self, request, revision_id, version_id, question_id=None):
        revision, version, question = self.load(revision_id, version_id, question_id)
        data = request.POST.copy()
        adding_option = data.get('editor_action') == 'add_option'
        if adding_option:
            try:
                count = int(data.get('options-TOTAL_FORMS', '0'))
            except ValueError:
                count = 0
            if 0 <= count < 100:
                data['options-TOTAL_FORMS'] = str(count + 1)
                data[f'options-{count}-order'] = str(count)
        form = AssessmentQuestionForm(data, instance=question, require_complete=not adding_option)
        options = OptionFormSet(data, instance=question, prefix='options', require_complete=not adding_option)
        valid_form, valid_options = form.is_valid(), options.is_valid()
        if valid_form and valid_options and not adding_option:
            question = form.save()
            options.instance = question
            question.options.update(is_correct=False)
            for option in options.forms:
                data = option.cleaned_data
                if data.get('DELETE'):
                    if option.instance.pk:
                        option.instance.delete()
                    continue
                if not data:
                    continue
                # Empty extra rows are not authored options just because their
                # order changed during keyboard/JS reordering.
                if not option.instance.pk and not data.get('text', '').strip() and option.prefix != options.correct_prefix:
                    continue
                item = option.save(commit=False)
                item.question = question
                item.is_correct = option.prefix == options.correct_prefix
                item.save()
            touch(revision)
            messages.success(request, 'تم حفظ السؤال وخياراته')
            return redirect('instructor:assessment', revision_id=revision.pk, version_id=version.pk)
        return self.render_to_response(self.get_context_data(revision=revision, version=version,
            form=form, options=options, correct_option=request.POST.get('correct_option', '')))


class AssessmentStructureView(AssessmentTeacherView):
    template_name = 'instructor/assessments/confirm.html'

    def load(self, revision_id, version_id, question_id, action):
        revision = self.own_revision(revision_id, editing=True)
        version = self.version(revision, version_id)
        if action not in ('delete', 'up', 'down') or (not question_id and action != 'delete'):
            raise Http404
        item = get_object_or_404(AssessmentQuestion, pk=question_id, version=version) if question_id else version
        return revision, version, item

    def get(self, request, revision_id, version_id, action, question_id=None):
        if action != 'delete':
            raise Http404
        revision, version, item = self.load(revision_id, version_id, question_id, action)
        return self.render_to_response(self.get_context_data(revision=revision, version=version, deleting_question=bool(question_id)))

    def post(self, request, revision_id, version_id, action, question_id=None):
        revision, version, item = self.load(revision_id, version_id, question_id, action)
        if action == 'delete':
            if request.POST.get('confirm') != 'yes':
                return self.render_to_response(self.get_context_data(revision=revision, version=version,
                    deleting_question=bool(question_id), confirmation_error=True))
            # Delete only the working snapshot. Stable assessment/history are preserved.
            item.delete()
            touch(revision)
            if not question_id and request.headers.get('X-Curriculum-Action') == '1':
                return JsonResponse({'redirect_url': reverse('instructor:assessments', args=[revision.pk]),
                    'message': 'تم حذف الاختبار من نسخة العمل'})
            messages.success(request, 'تم الحذف من نسخة العمل فقط')
            if not question_id:
                return redirect('instructor:assessments', revision_id=revision.pk)
        else:
            rows = list(version.questions.all())
            position = next(index for index, row in enumerate(rows) if row.pk == item.pk)
            neighbor = position + (-1 if action == 'up' else 1)
            if 0 <= neighbor < len(rows):
                rows[position], rows[neighbor] = rows[neighbor], rows[position]
                for index, row in enumerate(rows):
                    row.order = index
                AssessmentQuestion.objects.bulk_update(rows, ['order'])
                touch(revision)
                messages.success(request, 'تم حفظ ترتيب الأسئلة')
        return redirect('instructor:assessment', revision_id=revision.pk, version_id=version.pk)


class AssessmentQuestionOrderView(AssessmentTeacherView):
    http_method_names = ['post']

    def post(self, request, revision_id, version_id):
        revision = self.own_revision(revision_id, editing=True)
        version = self.version(revision, version_id)
        try:
            data = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({'error': 'طلب ترتيب غير صالح'}, status=400)
        if not isinstance(data, dict) or data.get('kind') != 'question' or data.get('module_id') is not None:
            return JsonResponse({'error': 'طلب ترتيب غير صالح'}, status=400)
        order, previous = data.get('order'), data.get('previous_order')
        rows = list(version.questions.all())
        current = [row.pk for row in rows]
        valid_ids = lambda values: isinstance(values, list) and len(values) == len(current) and all(type(pk) is int for pk in values) and len(set(values)) == len(values) and set(values) == set(current)
        if not valid_ids(order) or not valid_ids(previous):
            return JsonResponse({'error': 'يجب ترتيب أسئلة الاختبار نفسها دون حذف أو تكرار'}, status=400)
        if previous != current:
            return JsonResponse({'error': 'تغيّر ترتيب الأسئلة في نافذة أخرى، حدّث القائمة ثم أعد المحاولة'}, status=409)
        by_id = {row.pk: row for row in rows}
        for index, pk in enumerate(order):
            by_id[pk].order = index
        AssessmentQuestion.objects.bulk_update(rows, ['order'])
        touch(revision)
        return JsonResponse({'order': order})


@method_decorator(never_cache, name='dispatch')
class AssessmentPreviewView(LoginRequiredMixin, TemplateView):
    template_name = 'instructor/assessments/preview.html'
    http_method_names = ['get']
    review_answers = False

    def get(self, request, revision_id, version_id=None):
        revision = get_object_or_404(CourseRevision.objects.select_related('course'), pk=revision_id)
        owner = is_teacher(request.user) and revision.course.owner_id == request.user.pk
        reviewer = request.user.is_active and request.user.is_staff and request.user.has_perm('courses.review_course')
        if not (owner or reviewer) or (self.review_answers and not reviewer):
            raise PermissionDenied
        versions = revision.assessment_versions.select_related('module').prefetch_related('questions__options')
        version = get_object_or_404(versions, pk=version_id) if version_id else None
        # This private teacher/reviewer preview may show the key; student endpoints stay separate.
        include_key = owner or reviewer
        questions = []
        if version:
            for question in version.questions.all():
                options = [{'key': option.pk, 'text': option.text,
                    **({'correct': option.is_correct} if include_key else {})} for option in question.options.all()]
                questions.append({'key': question.pk, 'text': question.text, 'points': question.points, 'options': options})
        return self.render_to_response(dict(revision=revision, version=version, versions=versions,
            questions=questions, show_key=include_key, reviewer_allowed=reviewer,
            reviewer_preview=not owner, is_preview=True, hide_course_sidebar=True, teacher_space=True,
            teacher_section='courses', page_title='معاينة الاختبار', readiness_errors=readiness(version) if version else [],
            breadcrumbs=[{'label': revision.title, 'url': reverse('instructor:preview', args=[revision.pk])},
                {'label': 'معاينة الاختبارات', 'url': None}]))
