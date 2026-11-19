from django.db.models import Count
from urllib.parse import urlencode

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView
from django.views import View

from courses.details import lines, syllabus
from courses.models import Course
from .forms import CourseEnrollForm
from .models import StudentNotification
from django.contrib import messages
from django.db import transaction
from django.core.paginator import Paginator
from django.utils import timezone


@method_decorator(never_cache, name='dispatch')
class StudentEnrollCourseView(LoginRequiredMixin, View):
    def handle_no_permission(self):
        form = CourseEnrollForm(self.request.POST)
        target = reverse('course_detail', args=[form.cleaned_data['course'].slug]) if form.is_valid() else reverse('course_list')
        return redirect(reverse('sso_login') + '?' + urlencode({'next': target}))

    def post(self, request):
        form = CourseEnrollForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'هذه الدورة غير متاحة للالتحاق حاليًا. يمكنك استكشاف الدورات المتاحة.')
            return redirect('course_list')
        course = form.cleaned_data['course']
        with transaction.atomic():
            _, created = Course.students.through.objects.get_or_create(course=course, user=request.user)
            if created:
                StudentNotification.objects.get_or_create(user=request.user, course=course, defaults={
                    'title': 'أهلًا بك في دورتك الجديدة',
                    'body': f'تم التحاقك بدورة «{course.title}» بنجاح. تجدها الآن في دوراتي ويمكنك بدء التعلّم.'})
        if created:
            messages.success(request, f'تم التحاقك بدورة «{course.title}» بنجاح. يمكنك الآن بدء التعلّم.', extra_tags='enrollment')
        else:
            messages.info(request, 'أنت ملتحق بهذه الدورة مسبقًا. يمكنك متابعة التعلّم من هنا.', extra_tags='enrollment')
        return redirect('student_course_units', course_id=course.pk)


def joined_courses(user):
    from .favorites import with_favorites
    return with_favorites(Course.objects.filter(students=user).select_related('owner', 'subject').prefetch_related('modules').annotate(lesson_count=Count('modules__contents', distinct=True)), user)


def learning_action_label(progress):
    if not progress['available_content_count']:
        return None
    if progress['is_content_complete']:
        return 'مراجعة المحتوى'
    return 'استئناف التعلم' if progress['has_started'] else 'ابدأ التعلم'


@method_decorator(never_cache, name='dispatch')
class StudentPageView(LoginRequiredMixin, TemplateView):
    section = 'dashboard'
    page_titles = {
        'dashboard': 'لوحة التحكم', 'courses': 'دوراتي', 'favorites': 'المفضلة',
        'purchases': 'مشترياتي', 'notifications': 'مركز الإشعارات',
        'challenges': 'التحديات البرمجية',
    }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(section=self.section, page_title=self.page_titles.get(self.section, 'دوراتي'), unread_notification_count=StudentNotification.objects.filter(user=self.request.user, read_at__isnull=True).count())
        context['breadcrumbs'] = [{'label': 'لوحة التحكم', 'url': reverse('student_dashboard')}]
        if self.section == 'dashboard':
            context['breadcrumbs'][0]['url'] = None
        else:
            context['breadcrumbs'].append({'label': self.page_titles.get(self.section, 'دوراتي'), 'url': None})
        if self.section in ('dashboard', 'courses'):
            if self.section == 'dashboard':
                from .learning import learning_read_snapshot, student_progress_summary, student_courses_progress, resume_content
                from .models import CourseResume
                with learning_read_snapshot(self.request.user) as courses:
                    progress = student_courses_progress(self.request.user)
                    context['learning_summary'] = student_progress_summary(self.request.user)
                    context['course_count'] = context['learning_summary']['enrolled_course_count']
                    eligible = [pk for pk, row in progress.items() if row['available_content_count'] and not row['is_content_complete']]
                    latest = CourseResume.objects.filter(student=self.request.user, course_id__in=eligible).order_by('-last_visited_at', '-pk').first() if eligible else None
                    context['resume_card'] = None
                    if latest:
                        course = next(course for course in courses if course.pk == latest.course_id)
                        destination = resume_content(self.request.user, course.pk)
                        if destination:
                            context['resume_card'] = {'course': course, 'content': destination, 'progress': progress[course.pk]}
            elif 'course_id' not in self.kwargs:
                from .learning import learning_read_snapshot, student_courses_progress, resume_content
                with learning_read_snapshot(self.request.user) as courses:
                    progress = student_courses_progress(self.request.user)
                    for course in courses:
                        course.learning_progress = progress[course.pk]
                        course.learning_destination = resume_content(self.request.user, course.pk)
                        course.learning_action_label = learning_action_label(course.learning_progress)
                    context.update(courses=courses, course_count=len(courses))
        if self.section == 'purchases':
            context.update({
                'purchases': dict(empty_icon='bag', empty_title='لا توجد مشتريات لعرضها', empty_text='ستظهر هنا مشترياتك عندما تتاح خدمة الشراء. الشراء والدفع غير متاحين حاليًا.'),
            }[self.section])
        return context


class StudentFavoritesView(StudentPageView):
    section = 'favorites'
    template_name = 'students/dashboard/favorites.html'

    def get_context_data(self, **kwargs):
        from django.db.models import Exists, OuterRef
        from courses.cart import price_for
        from .favorites import with_favorites
        context = super().get_context_data(**kwargs)
        courses = with_favorites(Course.objects.filter(favorites__user=self.request.user, status='published').select_related('owner', 'subject').order_by('-favorites__created', '-favorites__pk'), self.request.user)
        courses = courses.annotate(is_joined=Exists(Course.students.through.objects.filter(user=self.request.user, course_id=OuterRef('pk'))))
        rows = list(courses)
        for course in rows:
            course.favorite_price = price_for(course)
        undo_id = self.request.session.pop('favorite_undo', None)
        undo_course = Course.objects.filter(pk=undo_id, status='published').first() if undo_id else None
        context.update(courses=rows, favorite_count=len(rows), undo_course=undo_course)
        return context


class StudentCourseListView(StudentPageView):
    section = 'courses'
    template_name = 'students/dashboard/courses.html'


class StudentCourseOverviewView(StudentPageView):
    section = 'courses'
    template_name = 'students/dashboard/course.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .learning import learning_read_snapshot, course_progress, resume_content
        with learning_read_snapshot(self.request.user, course_ids=[self.kwargs['course_id']]) as courses:
            if not courses:
                raise Http404
            course = courses[0]
            course.learning_progress = course_progress(self.request.user, course.pk)
            course.learning_destination = resume_content(self.request.user, course.pk)
            course.learning_action_label = learning_action_label(course.learning_progress)
        modules, total, _ = syllabus(course)
        from .models import ContentCompletion
        completed_ids = set(ContentCompletion.objects.filter(
            student=self.request.user, content__module__course=course,
        ).values_list('content_id', flat=True))
        for module in modules:
            for content in module.lesson_rows:
                content.is_completed = content.pk in completed_ids
        from courses.assessment_services import assessment_catalog
        assessment_rows = assessment_catalog(self.request.user, course.pk)
        for module in modules:
            module.assessment_rows = [row for row in assessment_rows if row['module_id'] == module.pk]
        context['all_assessment_rows'] = assessment_rows
        context['course_assessment_rows'] = [row for row in assessment_rows if row['module_id'] is None]
        context['course_progress'] = course.learning_progress
        context['breadcrumbs'][-1]['url'] = reverse('student_course_list')
        context['breadcrumbs'].append({'label': course.title, 'url': None})
        context.update(course=course, page_title=course.title, modules=modules, lesson_count=total,
                       outcomes=lines(course.learning_outcomes), requirements=lines(course.requirements),
                       audience=lines(course.target_audience))
        from courses.feedback import review_context
        context.update(review_context(course, self.request.user, self.request.GET))
        return context


class StudentCourseUnitsView(StudentCourseOverviewView):
    template_name = 'students/dashboard/units.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['breadcrumbs'][-1]['url'] = reverse('student_course_overview', args=[context['course'].pk])
        context['breadcrumbs'].append({'label': 'الوحدات', 'url': None})
        context['page_title'] = 'وحدات الدورة'
        return context


class StudentModuleView(StudentCourseOverviewView):
    template_name = 'students/dashboard/module.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        module = next((item for item in context['modules'] if item.pk == self.kwargs['module_id']), None)
        if module is None:
            raise Http404
        context['breadcrumbs'][-1]['url'] = reverse('student_course_overview', args=[context['course'].pk])
        context['breadcrumbs'].append({'label': 'الوحدات', 'url': reverse('student_course_units', args=[context['course'].pk])})
        context['breadcrumbs'].append({'label': module.title, 'url': None})
        context.update(selected_module=module, page_title=module.title,
                       module_number=context['modules'].index(module) + 1)
        return context


class StudentLessonView(StudentCourseOverviewView):
    template_name = 'students/dashboard/player.html'

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        lesson = context.get('lesson')
        if self.request.method == 'GET' and lesson is not None:
            def record_visit(rendered_response):
                if rendered_response.status_code == 200:
                    from .learning import record_content_visit
                    record_content_visit(self.request.user, context['course'].pk, lesson.pk)
            response.add_post_render_callback(record_visit)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(learning_mode=True, hide_course_sidebar=True)
        modules = context['modules']
        lessons = [lesson for module in modules for lesson in module.lesson_rows]
        lesson = None
        module = modules[0] if modules else None
        if 'content_id' in self.kwargs:
            lesson = next((item for item in lessons if item.pk == self.kwargs['content_id']), None)
            if lesson is None:
                raise Http404
            module = next(item for item in modules if item.pk == lesson.module_id)
        elif 'module' in self.request.GET:
            module = next((item for item in modules if str(item.pk) == self.request.GET['module']), None)
            if module is None:
                raise Http404
            lesson = next(iter(module.lesson_rows), None)
        elif lessons:
            lesson = lessons[0]
            module = next(item for item in modules if item.pk == lesson.module_id)
        index = lessons.index(lesson) if lesson else -1
        context['breadcrumbs'][-1]['url'] = reverse('student_course_overview', args=[context['course'].pk])
        context['breadcrumbs'].append({'label': 'الوحدات', 'url': reverse('student_course_units', args=[context['course'].pk])})
        if module:
            context['breadcrumbs'].append({'label': module.title, 'url': reverse('student_module', args=[context['course'].pk, module.pk]) if lesson else None})
        if lesson:
            context['breadcrumbs'].append({'label': lesson.item.title, 'url': None})
            context['page_title'] = lesson.item.title
        elif not module:
            context['breadcrumbs'].append({'label': 'مشغّل الدروس', 'url': None})
        context.update(lesson=lesson, selected_module=module,
                       lesson_number=index + 1 if index >= 0 else None,
                       previous_lesson=lessons[index - 1] if index > 0 else None,
                       next_lesson=lessons[index + 1] if index >= 0 and index + 1 < len(lessons) else None)
        next_lesson = context['next_lesson']
        context['next_module'] = next(
            (item for item in modules if item.pk == next_lesson.module_id), None
        ) if next_lesson and next_lesson.module_id != module.pk else None
        context['next_assessment'] = None
        if lesson and (next_lesson is None or context['next_module'] is not None):
            # Use only the already-authorized published catalog, in its existing order.
            candidates = module.assessment_rows
            if not candidates and next_lesson is None:
                candidates = context['course_assessment_rows']
            context['next_assessment'] = next(iter(candidates), None)
        if lesson:
            if lesson.content_type.model in ('image', 'file'):
                asset = lesson.item.file
                try:
                    context['lesson_media_available'] = bool(asset and asset.storage.exists(asset.name))
                except OSError:
                    context['lesson_media_available'] = False
            from courses.feedback import comment_context
            context.update(comment_context(context['course'], lesson, self.request.user, self.request.GET))
        return context


@method_decorator(never_cache, name='dispatch')
class StudentCourseDetailView(LoginRequiredMixin, TemplateView):
    """Keep existing bookmarks and enrollment redirects working."""
    def get(self, request, *args, **kwargs):
        course = get_object_or_404(joined_courses(request.user), pk=kwargs['pk'])
        target = reverse('student_course_learn', args=[course.pk])
        if 'module_id' in kwargs:
            module = get_object_or_404(course.modules, pk=kwargs['module_id'])
            target = reverse('student_module', args=[course.pk, module.pk])
        return redirect(target)


class StudentNotificationsView(StudentPageView):
    section = 'notifications'
    template_name = 'students/dashboard/notifications.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        page = Paginator(StudentNotification.objects.filter(user=self.request.user).select_related('course'), 20).get_page(self.request.GET.get('page'))
        enrolled = set(joined_courses(self.request.user).values_list('pk', flat=True))
        for notice in page.object_list:
            notice.course_url = reverse('student_course_overview', args=[notice.course_id]) if notice.course_id in enrolled else None
        context.update(notifications=page.object_list, page_obj=page)
        return context


@method_decorator(never_cache, name='dispatch')
class StudentNotificationReadView(LoginRequiredMixin, View):
    def handle_no_permission(self):
        return redirect(reverse('sso_login') + '?' + urlencode({'next': reverse('student_notifications')}))

    def post(self, request, notification_id=None):
        notices = StudentNotification.objects.filter(user=request.user)
        if notification_id is not None:
            get_object_or_404(notices, pk=notification_id)
            notices = notices.filter(pk=notification_id)
        updated = notices.filter(read_at__isnull=True).update(read_at=timezone.now())
        if updated:
            messages.success(request, 'تم تحديد الإشعارات كمقروءة.')
        return redirect('student_notifications')
