from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.db.models import Prefetch, prefetch_related_objects
from django.shortcuts import get_object_or_404
from django.views.generic import DetailView
from .models import Course, Module, Content
from .enrollment import free_demo_courses


def lines(value):
    return [line.strip() for line in value.splitlines() if line.strip()]


def syllabus(course):
    # Reuse already-prefetched modules when processing several courses together.
    modules = list(course.modules.all())
    prefetch_related_objects(modules, 'contents__item', 'contents__content_type')
    first_preview = None
    total = 0
    for module in modules:
        module.lesson_rows = []
        for content in module.contents.all():
            if content.item is None:
                continue
            total += 1
            module.lesson_rows.append(content)
            if first_preview is None and content.is_preview:
                first_preview = content
    return modules, total, first_preview


@method_decorator(never_cache, name='dispatch')
class CourseDetailsView(DetailView):
    model = Course
    template_name = 'courses/course/detail.html'

    def get_queryset(self):
        from students.favorites import with_favorites
        return with_favorites(Course.objects.filter(status='published').select_related('owner', 'subject'), self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        modules, total, preview = syllabus(self.object)
        from .models import Assessment
        tests = Assessment.objects.filter(course=self.object, status='published',
            published_version__course_revision_id=self.object.published_revision_id,
            published_version__course_revision__status='approved').select_related('published_version__module__source')
        public_tests = []
        for test in tests:
            if not test.is_available:
                continue
            version = test.published_version
            module = version.module
            if module and (module.source_id is None or module.source.course_id != self.object.pk):
                continue
            public_tests.append({'title': version.title, 'module_id': module.source_id if module else None})
        for module in modules:
            module.public_assessments = [test for test in public_tests if test['module_id'] == module.pk]
        context['public_course_assessments'] = [test for test in public_tests if test['module_id'] is None]
        context['assessment_count'] = len(public_tests)
        context['free_demo_enrollment'] = free_demo_courses(Course.objects.filter(pk=self.object.pk)).exists()
        context['already_enrolled'] = self.request.user.is_authenticated and self.object.students.filter(pk=self.request.user.pk).exists()
        from .cart import price_for
        context['published_price'] = price_for(self.object)
        context.update(modules=modules, lesson_count=total, first_preview=preview,
                       outcomes=lines(self.object.learning_outcomes),
                       requirements=lines(self.object.requirements),
                       audience=lines(self.object.target_audience))
        from .feedback import review_context
        context.update(review_context(self.object, self.request.user, self.request.GET))
        return context


class LessonPreviewView(DetailView):
    model = Content
    pk_url_kwarg = 'content_id'
    template_name = 'courses/course/preview.html'
    context_object_name = 'lesson'

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        response['X-Frame-Options'] = 'SAMEORIGIN'
        return response

    def get_template_names(self):
        if self.request.GET.get('embed') == '1':
            return ['courses/course/preview-embed.html']
        return [self.template_name]

    def get_queryset(self):
        return Content.objects.filter(is_preview=True, module__course__status='published', module__course__slug=self.kwargs['slug']).select_related('module__course', 'content_type').prefetch_related('item')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.item is None:
            from django.http import Http404
            raise Http404
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['course'] = self.object.module.course
        return context
