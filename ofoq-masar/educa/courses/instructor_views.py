from uuid import uuid4
import json
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction, IntegrityError, OperationalError
from django.db.models import Count, Max, OuterRef, Subquery, Q, Prefetch
from django.shortcuts import get_object_or_404, redirect
from django.http import FileResponse, Http404, JsonResponse
from django.views.decorators.http import require_GET
from pathlib import Path
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from .models import Course, CourseRevision, RevisionModule, RevisionContent, TeacherNotification
from .instructor_services import is_teacher, working_revision, editable, submit_revision, validate_revision, restore_revision, discard_revision
from .instructor_forms import RevisionForm, UnitForm, LessonForm
from .revision_requirements import validate_details


def details_requirements(revision):
    try:
        validate_details(revision)
    except ValidationError as exc:
        return exc.messages
    return []


def review_requirements(revision):
    if revision.status in ['pending', 'approved']:
        return []
    try:
        validate_revision(revision)
    except ValidationError as exc:
        return [message.rstrip('. ') for message in exc.messages]
    return []


@method_decorator(never_cache, name='dispatch')
class TeacherView(LoginRequiredMixin, TemplateView):
    requires_details = False
    template_name = 'instructor/dashboard.html'
    page_title = 'لوحة التحكم'
    section = 'dashboard'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not is_teacher(request.user):
            raise PermissionDenied
        if request.user.is_authenticated and self.requires_details:
            revision_id = kwargs.get('revision_id')
            if kwargs.get('module_id'):
                revision_id = get_object_or_404(RevisionModule, pk=kwargs['module_id'], revision__course__owner=request.user).revision_id
            if kwargs.get('lesson_id'):
                revision_id = get_object_or_404(RevisionContent, pk=kwargs['lesson_id'], module__revision__course__owner=request.user).module.revision_id
            revision = get_object_or_404(CourseRevision, pk=revision_id, course__owner=request.user)
            missing = details_requirements(revision)
            if missing:
                messages.info(request, 'أكمل بيانات الدورة أولًا: ' + '، '.join(missing))
                if revision.status in ['draft', 'rejected']:
                    return redirect('instructor:edit', revision_id=revision.pk)
                return redirect('instructor:course', course_id=revision.course_id)
        if request.method == 'POST':
            with transaction.atomic():
                return super().dispatch(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def own_course(self, pk):
        query = Course.objects.select_for_update() if self.request.method == 'POST' else Course.objects.all()
        return get_object_or_404(query, pk=pk, owner=self.request.user)

    def own_revision(self, pk, editing=False):
        candidate = get_object_or_404(CourseRevision, pk=pk, course__owner=self.request.user)
        self.own_course(candidate.course_id)
        query = CourseRevision.objects.select_for_update() if self.request.method == 'POST' else CourseRevision.objects.all()
        revision = query.select_related('course', 'subject').get(pk=pk)
        if editing:
            try: editable(revision)
            except ValidationError: raise PermissionDenied('اسحب النسخة من المراجعة قبل التعديل.')
        return revision

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['course_form'] = isinstance(context.get('form'), RevisionForm)
        context.setdefault('setup_step', 'details' if context['course_form'] else 'curriculum')
        revision = context.get('revision')
        # A failed ModelForm can mutate its instance without saving it. Gate on
        # persisted metadata, while leaving the bound form intact for correction.
        if revision and context['course_form'] and context['form'].is_bound:
            revision = CourseRevision.objects.get(pk=revision.pk)
        context['details_requirements'] = details_requirements(revision) if revision else []
        context['curriculum_available'] = revision is not None and not context['details_requirements']
        context['review_requirements'] = review_requirements(revision) if revision else []
        context['review_available'] = revision is not None and not context['review_requirements']
        context.update(page_title=self.page_title, teacher_section=self.section, teacher_space=True, hide_course_sidebar=True,
            breadcrumbs=[{'label': 'مساحة المعلّم', 'url': reverse('instructor:dashboard')}, {'label': self.page_title, 'url': None}],
            teacher_unread=TeacherNotification.objects.filter(user=self.request.user, read_at__isnull=True).count())
        notices = TeacherNotification.objects.filter(user=self.request.user, announced_at__isnull=True)
        for notice in list(notices[:3]):
            if notices.filter(pk=notice.pk, announced_at__isnull=True).update(announced_at=timezone.now()):
                messages.info(self.request, notice.body)
        return context

    def get(self, request, *args, **kwargs):
        courses = Course.objects.filter(owner=request.user)
        context = self.get_context_data(published_count=courses.filter(status='published').count(),
            draft_count=CourseRevision.objects.filter(course__owner=request.user, status='draft').count(),
            pending_count=CourseRevision.objects.filter(course__owner=request.user, status='pending').count())
        return self.render_to_response(context)


class TeacherCoursesView(TeacherView):
    template_name = 'instructor/courses.html'
    page_title = 'دوراتي'
    section = 'courses'

    def get(self, request):
        work = CourseRevision.objects.filter(course_id=OuterRef('pk'), status__in=['draft', 'pending', 'rejected'])
        revision_cards = CourseRevision.objects.select_related('subject').annotate(card_units=Count('modules', distinct=True), card_lessons=Count('modules__contents', distinct=True))
        courses = Course.objects.filter(owner=request.user).select_related('subject').prefetch_related(Prefetch('revisions', queryset=revision_cards)).annotate(work_status=Subquery(work.values('status')[:1]), card_units=Count('modules', distinct=True), card_lessons=Count('modules__contents', distinct=True))
        query = request.GET.get('q', '').strip()[:200]
        state = request.GET.get('status', '')
        archive_view = state == 'archived'
        counts = Course.objects.filter(owner=request.user).aggregate(
            active=Count('pk', filter=~Q(status='archived')), archived=Count('pk', filter=Q(status='archived')))
        if not archive_view: courses = courses.exclude(status='archived')
        if query: courses = courses.filter(Q(title__icontains=query) | Q(revisions__title__icontains=query)).distinct()
        if state in ['draft', 'pending', 'rejected']: courses = courses.filter(work_status=state)
        elif state in ['published', 'archived']: courses = courses.filter(status=state)
        else: state = ''
        page = Paginator(courses.order_by('-created', '-pk'), 12).get_page(request.GET.get('page'))
        for course in page:
            course.work = next((r for r in course.revisions.all() if r.status in ['draft', 'pending', 'rejected']), None)
            course.display_title = course.work.title if course.work else course.title
            course.card_data = course.work or course
            course.unit_count = course.card_data.card_units
            course.lesson_count = course.card_data.card_lessons
        params = request.GET.copy(); params.pop('page', None)
        return self.render_to_response(self.get_context_data(courses=page, page_obj=page, query=query, state=state,
            archive_view=archive_view, course_counts=counts, pagination_query=params.urlencode()))


class CourseWorkspaceView(TeacherView):
    template_name = 'instructor/course.html'
    page_title = 'إدارة الدورة'
    section = 'courses'

    def get(self, request, course_id):
        course = self.own_course(course_id)
        work = course.revisions.filter(status__in=['draft', 'pending', 'rejected']).first()
        data = work or course
        summary = data.modules.aggregate(units=Count('pk', distinct=True), contents=Count('contents', distinct=True))
        next_step, next_label, continue_url = 'details', 'أكمل بيانات الدورة', None
        can_edit = work is not None and work.status in ['draft', 'rejected']
        if work:
            if work.status == 'pending' or (work.status == 'rejected' and not review_requirements(work)):
                next_step = 'review'
                next_label = 'متابعة المراجعة' if work.status == 'pending' else 'عرض ملاحظات المراجعة'
            elif not details_requirements(work):
                next_step, next_label = 'review', 'راجع الدورة للنشر'
                try: validate_revision(work)
                except ValidationError: next_step, next_label = 'curriculum', 'أكمل منهج الدورة'
            continue_url = reverse('instructor:edit', args=[work.pk]) if next_step == 'details' else reverse('instructor:revision', args=[work.pk]) + '?step=' + next_step
        return self.render_to_response(self.get_context_data(managed_course=course, revision=work, course_data=data,
            summary=summary, next_step=next_step, next_label=next_label, continue_url=continue_url, can_edit=can_edit,
            assessment_revision_id=work.pk if work else course.published_revision_id))


class CourseVersionsView(TeacherView):
    template_name = 'instructor/versions.html'
    page_title = 'نسخ الدورة'
    section = 'courses'

    def get(self, request, course_id):
        course = self.own_course(course_id)
        work = course.revisions.filter(status__in=['draft', 'pending', 'rejected']).first()
        versions = course.revisions.select_related('reviewed_by', 'restored_from').order_by('-number', '-pk')
        page = Paginator(versions, 12).get_page(request.GET.get('page'))
        context = self.get_context_data(managed_course=course, work=work, published=course.published_revision,
            versions=page, page_obj=page, pagination_query='')
        context['breadcrumbs'] = [{'label': 'دوراتي', 'url': reverse('instructor:courses')},
            {'label': course.title, 'url': reverse('instructor:course', args=[course.pk])}, {'label': 'نسخ الدورة', 'url': None}]
        return self.render_to_response(context)


class VersionActionView(TeacherView):
    http_method_names = ['post']

    def post(self, request, revision_id, action):
        revision = self.own_revision(revision_id)
        back_url = reverse('instructor:versions', args=[revision.course_id])
        if action not in ['restore', 'discard']: raise Http404
        if request.POST.get('confirm') != 'yes':
            messages.error(request, 'يرجى تأكيد الإجراء قبل تنفيذه')
            return redirect(back_url)
        try:
            if action == 'restore':
                restored = restore_revision(revision, request.user)
                messages.success(request, f'تمت استعادة النسخة {revision.number} كمسودة جديدة رقم {restored.number}')
                return redirect('instructor:revision', revision_id=restored.pk)
            discard_revision(revision, request.user)
            messages.success(request, 'تم تجاهل التعديلات، والنسخة محفوظة في السجل للمعاينة')
        except ValidationError as exc:
            for message in exc.messages: messages.error(request, message)
        except (IntegrityError, OperationalError):
            messages.error(request, 'تغيّرت النسخ أثناء تنفيذ الطلب؛ حدّث الصفحة ثم أعد المحاولة')
        return redirect(back_url)


class CourseLifecycleView(TeacherView):
    template_name = 'instructor/confirm-course-action.html'
    section = 'courses'

    def load(self, course_id, action):
        course = self.own_course(course_id)
        if action == 'delete':
            if (course.status != 'draft' or course.published_revision_id or
                    course.revisions.filter(status__in=['approved', 'pending']).exists() or
                    course.students.exists() or course.chat_messages.exists()):
                raise PermissionDenied('الحذف متاح للمسودة غير المنشورة فقط. اسحبها من المراجعة أولًا، واستخدم الأرشفة للدورة المنشورة.')
            self.page_title = 'حذف المسودة'
        elif action == 'archive' and course.status == 'published':
            self.page_title = 'أرشفة الدورة'
        elif action == 'restore' and course.status == 'archived':
            self.page_title = 'إلغاء أرشفة الدورة'
        else:
            raise PermissionDenied
        return course

    def get(self, request, course_id, action):
        course = self.load(course_id, action)
        return self.render_to_response(self.get_context_data(managed_course=course, action=action))

    def post(self, request, course_id, action):
        course = self.load(course_id, action)
        if request.POST.get('confirm') != 'yes':
            return self.render_to_response(self.get_context_data(managed_course=course, action=action, confirmation_error=True), status=400)
        if action == 'delete':
            course.delete()
            messages.success(request, 'تم حذف المسودة.')
            return redirect('instructor:courses')
        course.status = 'archived' if action == 'archive' else 'published'
        course.save(update_fields=['status'])
        messages.success(request, 'تمت أرشفة الدورة مع الحفاظ على وصول طلابها.' if action == 'archive' else 'تم إلغاء الأرشفة وإظهار الدورة مجددًا.')
        return redirect('instructor:course', course_id=course.pk)


class CourseCreateView(TeacherView):
    template_name = 'instructor/form.html'
    page_title = 'إنشاء دورة'
    section = 'courses'

    def get(self, request):
        return self.render_to_response(self.get_context_data(form=RevisionForm(), back_url=reverse('instructor:courses')))

    def post(self, request):
        form = RevisionForm(request.POST, request.FILES)
        if form.is_valid():
            revision = form.save(commit=False)
            course = Course.objects.create(owner=request.user, subject=revision.subject, title=revision.title, overview='', slug='course-' + uuid4().hex[:16], status='draft')
            revision.course, revision.number = course, 1
            revision.save()
            messages.success(request, 'تم حفظ الدورة كمسودة. أضف الوحدات والمحتوى ثم أرسلها للمراجعة')
            return redirect('instructor:revision', revision_id=revision.pk)
        return self.render_to_response(self.get_context_data(form=form, back_url=reverse('instructor:courses')))


class StartRevisionView(TeacherView):
    http_method_names = ['post']

    def post(self, request, course_id):
        course = self.own_course(course_id)
        try:
            revision = working_revision(course)
        except (FileNotFoundError, ValidationError) as exc:
            messages.error(request, ' · '.join(exc.messages) if isinstance(exc, ValidationError) else 'تعذّر تجهيز نسخة التعديل بسبب ملف منشور مفقود. راجع إدارة الأكاديمية لاستعادته.')
            return redirect('instructor:course', course_id=course.pk)
        return redirect('instructor:revision', revision_id=revision.pk)


class RevisionWorkspaceView(TeacherView):
    requires_details = True
    template_name = 'instructor/revision.html'
    page_title = 'إدارة الوحدات والمحتوى'
    section = 'courses'

    def get(self, request, revision_id):
        revision = self.own_revision(revision_id)
        step = request.GET.get('step', 'review' if revision.status in ['pending', 'rejected', 'approved'] else 'curriculum')
        if step not in ['curriculum', 'review']: raise Http404
        if step == 'review' and review_requirements(revision):
            messages.info(request, 'لفتح المراجعة والنشر: ' + '، '.join(review_requirements(revision)))
            return redirect(reverse('instructor:revision', args=[revision.pk]) + '?step=curriculum')
        modules = list(revision.modules.prefetch_related('contents'))
        selected = modules[0] if modules else None
        if request.GET.get('module'):
            selected = next((m for m in modules if str(m.pk) == request.GET['module']), None)
            if selected is None: raise Http404
        review_errors = []
        if step == 'review' and revision.status in ['draft', 'rejected']:
            try: validate_revision(revision)
            except ValidationError as exc: review_errors = [message.rstrip('. ') for message in exc.messages]
        assessment_summary = revision.assessment_versions.aggregate(
            assessment_count=Count('pk', distinct=True), assessment_question_count=Count('questions')) if step == 'review' else {}
        return self.render_to_response(self.get_context_data(revision=revision, modules=modules, selected_module=selected,
            lesson_count=sum(len(m.contents.all()) for m in modules), setup_step=step, review_errors=review_errors,
            review_ready=not review_errors, can_edit=revision.status in ['draft', 'rejected'], **assessment_summary))


class RevisionReorderView(TeacherView):
    requires_details = True
    http_method_names = ['post']

    def post(self, request, revision_id):
        revision = self.own_revision(revision_id, True)
        if request.content_type != 'application/json' or len(request.body) > 65536:
            return JsonResponse({'error': 'طلب ترتيب غير صالح'}, status=400)
        try:
            data = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({'error': 'طلب ترتيب غير صالح'}, status=400)
        if not isinstance(data, dict): return JsonResponse({'error': 'طلب غير صالح'}, status=400)
        if data.get('kind') == 'module':
            query = revision.modules.all()
        elif data.get('kind') == 'lesson' and type(data.get('module_id')) is int:
            module = get_object_or_404(RevisionModule, pk=data['module_id'], revision=revision)
            query = module.contents.all()
        else:
            return JsonResponse({'error': 'نوع ترتيب غير صالح'}, status=400)
        rows = list(query)
        current = [row.pk for row in rows]
        order, previous = data.get('order'), data.get('previous_order')
        if (not isinstance(order, list) or not isinstance(previous, list) or
                any(type(pk) is not int for pk in order + previous) or
                len(order) != len(current) or len(set(order)) != len(order) or set(order) != set(current)):
            return JsonResponse({'error': 'يجب إرسال عناصر القائمة نفسها دون حذف أو تكرار'}, status=400)
        if previous != current:
            return JsonResponse({'error': 'تغيّر المنهج في نافذة أخرى، حدّث الصفحة ثم أعد المحاولة'}, status=409)
        positions = {pk: index for index, pk in enumerate(order)}
        for row in rows: row.order = positions[row.pk]
        query.model.objects.bulk_update(rows, ['order'])
        CourseRevision.objects.filter(pk=revision.pk).update(updated=timezone.now())
        return JsonResponse({'order': order})


class RevisionEditView(TeacherView):
    template_name = 'instructor/form.html'
    page_title = 'بيانات الدورة'
    section = 'courses'

    def get(self, request, revision_id):
        revision = self.own_revision(revision_id, True)
        return self.render_to_response(self.get_context_data(form=RevisionForm(instance=revision), revision=revision, back_url=reverse('instructor:revision', args=[revision.pk])))

    def post(self, request, revision_id):
        revision = self.own_revision(revision_id, True)
        form = RevisionForm(request.POST, request.FILES, instance=revision)
        if form.is_valid():
            form.save(); messages.success(request, 'تم حفظ بيانات المسودة.')
            return redirect('instructor:revision', revision_id=revision.pk)
        return self.render_to_response(self.get_context_data(form=form, revision=revision, back_url=reverse('instructor:revision', args=[revision.pk])))


class RevisionActionView(TeacherView):
    http_method_names = ['post']

    def post(self, request, revision_id, action):
        revision = self.own_revision(revision_id)
        try:
            if action == 'submit':
                submit_revision(revision)
                messages.success(request, 'تم إرسال النسخة للمراجعة.')
            elif action == 'withdraw':
                from .instructor_services import withdraw_revision
                withdraw_revision(revision, request.user)
                messages.success(request, 'تم سحب النسخة إلى المسودات.')
            else: raise PermissionDenied
        except ValidationError as exc:
            for error in exc.messages: messages.error(request, error)
        return redirect('instructor:revision', revision_id=revision.pk)


class ContentEditorView(TeacherView):
    requires_details = True
    def get_template_names(self):
        if self.request.headers.get('X-Editor-Dialog') == '1':
            return ['instructor/editor-form.html']
        return super().get_template_names()

    def editor_redirect(self, url):
        if self.request.headers.get('X-Editor-Dialog') == '1':
            return JsonResponse({'redirect_url': url})
        return redirect(url)

    def editor_errors(self, form):
        return JsonResponse({'errors': form.errors.get_json_data()}, status=422)


class UnitEditView(ContentEditorView):
    template_name = 'instructor/form.html'
    page_title = 'بيانات الوحدة'
    section = 'courses'

    def load(self, revision_id=None, module_id=None):
        unit = get_object_or_404(RevisionModule, pk=module_id, revision__course__owner=self.request.user) if module_id else None
        revision = self.own_revision(unit.revision_id if unit else revision_id, True)
        return unit, revision

    def get(self, request, revision_id=None, module_id=None):
        unit, revision = self.load(revision_id, module_id)
        return self.render_to_response(self.get_context_data(form=UnitForm(instance=unit), revision=revision, back_url=reverse('instructor:revision', args=[revision.pk]) + (f'?step=curriculum&module={unit.pk}' if unit else '?step=curriculum')))

    def post(self, request, revision_id=None, module_id=None):
        unit, revision = self.load(revision_id, module_id)
        form = UnitForm(request.POST, instance=unit)
        if form.is_valid():
            obj = form.save(commit=False)
            if unit is None: obj.order = (revision.modules.aggregate(last=Max('order'))['last'] or 0) + 1
            obj.revision = revision; obj.save()
            messages.success(request, 'تم حفظ الوحدة.')
            return self.editor_redirect(reverse('instructor:revision', args=[revision.pk]) + f'?step=curriculum&module={obj.pk}')
        if request.headers.get('X-Editor-Dialog') == '1': return self.editor_errors(form)
        return self.render_to_response(self.get_context_data(form=form, revision=revision, back_url=reverse('instructor:revision', args=[revision.pk]) + '?step=curriculum'))


class LessonEditView(ContentEditorView):
    template_name = 'instructor/form.html'
    page_title = 'بيانات المحتوى'
    section = 'courses'

    def load(self, module_id=None, lesson_id=None):
        lesson = get_object_or_404(RevisionContent, pk=lesson_id, module__revision__course__owner=self.request.user) if lesson_id else None
        module = lesson.module if lesson else get_object_or_404(RevisionModule, pk=module_id, revision__course__owner=self.request.user)
        revision = self.own_revision(module.revision_id, True)
        return lesson, module, revision

    def get(self, request, module_id=None, lesson_id=None):
        lesson, module, revision = self.load(module_id, lesson_id)
        kind = request.GET.get('kind', 'text')
        if kind not in dict(RevisionContent.KINDS): kind = 'text'
        return self.render_to_response(self.get_context_data(form=LessonForm(instance=lesson, initial={'kind': lesson.kind if lesson else kind}), revision=revision, back_url=reverse('instructor:revision', args=[revision.pk]) + f'?step=curriculum&module={module.pk}'))

    def post(self, request, module_id=None, lesson_id=None):
        lesson, module, revision = self.load(module_id, lesson_id)
        form = LessonForm(request.POST, request.FILES, instance=lesson)
        if form.is_valid():
            obj = form.save(commit=False)
            if lesson is None: obj.order = (module.contents.aggregate(last=Max('order'))['last'] or 0) + 1
            obj.module = module; obj.save()
            messages.success(request, 'تم حفظ المحتوى')
            return self.editor_redirect(reverse('instructor:revision', args=[revision.pk]) + f'?step=curriculum&module={module.pk}')
        if request.headers.get('X-Editor-Dialog') == '1': return self.editor_errors(form)
        return self.render_to_response(self.get_context_data(form=form, revision=revision, back_url=reverse('instructor:revision', args=[revision.pk]) + f'?step=curriculum&module={module.pk}'))


class StructureActionView(TeacherView):
    requires_details = True
    http_method_names = ['post']

    def post(self, request, revision_id, kind, object_id, action):
        revision = self.own_revision(revision_id, True)
        if kind == 'module': query = revision.modules.all()
        elif kind == 'lesson': query = RevisionContent.objects.filter(module__revision=revision)
        else: raise PermissionDenied
        obj = get_object_or_404(query, pk=object_id)
        notice = 'تم حفظ الترتيب'
        if action == 'delete':
            obj.delete()
            notice = 'تم حذف الوحدة من المسودة' if kind == 'module' else 'تم حذف المحتوى من المسودة'
        elif action in ['up', 'down']:
            siblings = list(query.filter(module=obj.module) if kind == 'lesson' else query)
            index = next(i for i, item in enumerate(siblings) if item.pk == obj.pk)
            target = index + (-1 if action == 'up' else 1)
            if 0 <= target < len(siblings):
                siblings[index], siblings[target] = siblings[target], siblings[index]
                for position, item in enumerate(siblings): item.order = position
                query.model.objects.bulk_update(siblings, ['order'])
        else: raise PermissionDenied
        destination = reverse('instructor:revision', args=[revision.pk]) + (f'?step=curriculum&module={obj.module_id}' if kind == 'lesson' else '?step=curriculum')
        if request.headers.get('X-Curriculum-Action') == '1':
            return JsonResponse({'redirect_url': destination, 'message': notice})
        messages.success(request, notice)
        return redirect(destination)


class RevisionPreviewView(TemplateView):
    template_name = 'instructor/preview.html'

    @method_decorator(never_cache)
    def dispatch(self, request, *args, **kwargs):
        self.revision = get_object_or_404(CourseRevision.objects.select_related('course__owner', 'subject'), pk=kwargs['revision_id'])
        owner = is_teacher(request.user) and self.revision.course.owner_id == request.user.pk
        reviewer = request.user.is_authenticated and request.user.is_active and request.user.is_staff and request.user.has_perm('courses.review_course')
        if not (owner or reviewer): raise PermissionDenied
        self.reviewer_preview = not owner
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        modules = list(self.revision.modules.prefetch_related('contents'))
        lessons = []
        for module in modules:
            module.lesson_rows = list(module.contents.all())
            lessons.extend(module.lesson_rows)
        mode = self.request.GET.get('view', 'overview')
        if mode not in ['overview', 'units', 'module', 'lesson']: raise Http404
        selected_module = selected_lesson = previous_lesson = next_lesson = None
        if mode in ['module', 'lesson']:
            value = self.request.GET.get('id', '')
            if not value.isdecimal() or len(value) > 18: raise Http404
            if mode == 'module':
                selected_module = next((m for m in modules if m.pk == int(value)), None)
                if selected_module is None: raise Http404
            else:
                selected_lesson = next((lesson for lesson in lessons if lesson.pk == int(value)), None)
                if selected_lesson is None: raise Http404
                selected_module = next(m for m in modules if m.pk == selected_lesson.module_id)
                index = lessons.index(selected_lesson)
                previous_lesson = lessons[index - 1] if index else None
                next_lesson = lessons[index + 1] if index + 1 < len(lessons) else None
        preview_url = reverse('instructor:preview', args=[self.revision.pk])
        crumbs = [{'label': self.revision.title, 'url': preview_url if mode != 'overview' else None}]
        if mode != 'overview': crumbs.append({'label': 'الوحدات', 'url': preview_url + '?view=units' if mode != 'units' else None})
        if selected_module: crumbs.append({'label': selected_module.title, 'url': preview_url + f'?view=module&id={selected_module.pk}' if mode == 'lesson' else None})
        if selected_lesson: crumbs.append({'label': selected_lesson.title, 'url': None})
        context.update(revision=self.revision, modules=modules, preview_mode=mode, preview_url=preview_url,
            lesson_count=len(lessons), selected_module=selected_module, selected_lesson=selected_lesson,
            previous_lesson=previous_lesson, next_lesson=next_lesson,
            lesson_number=lessons.index(selected_lesson) + 1 if selected_lesson else None,
            outcomes=[line.strip() for line in self.revision.learning_outcomes.splitlines() if line.strip()],
            requirements=[line.strip() for line in self.revision.requirements.splitlines() if line.strip()],
            audience=[line.strip() for line in self.revision.target_audience.splitlines() if line.strip()],
            page_title='معاينة نسخة الدورة', teacher_section='courses', teacher_space=True, hide_course_sidebar=True, is_preview=True,
            reviewer_preview=self.reviewer_preview,
            breadcrumbs=crumbs)
        return context


class TeacherNotificationsView(TeacherView):
    template_name = 'instructor/notifications.html'
    page_title = 'الإشعارات'
    section = 'notifications'

    def get(self, request):
        page = Paginator(TeacherNotification.objects.filter(user=request.user).select_related('revision'), 20).get_page(request.GET.get('page'))
        return self.render_to_response(self.get_context_data(notifications=page, page_obj=page))

    def post(self, request):
        TeacherNotification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
        messages.success(request, 'تم تحديد الإشعارات كمقروءة.')
        return redirect('instructor:notifications')


@never_cache
@require_GET
def revision_asset(request, name):
    revision = CourseRevision.objects.filter(Q(cover=name) | Q(modules__contents__file=name)).select_related('course').first()
    if not revision:
        raise Http404
    owner = is_teacher(request.user) and revision.course.owner_id == request.user.pk
    reviewer = request.user.is_authenticated and request.user.is_active and request.user.is_staff and request.user.has_perm('courses.review_course')
    if not (owner or reviewer): raise PermissionDenied
    asset = revision.cover if revision.cover.name == name else RevisionContent.objects.get(module__revision=revision, file=name).file
    try: stream = asset.open('rb')
    except FileNotFoundError: raise Http404
    image = Path(name).suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg']
    response = FileResponse(stream, as_attachment=not image, filename=Path(name).name)
    response['Content-Security-Policy'] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
    response['X-Content-Type-Options'] = 'nosniff'
    return response
