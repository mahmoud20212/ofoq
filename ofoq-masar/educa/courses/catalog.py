from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.db.models import Count, Q, Value
from django.db.models.functions import Concat
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import ListView

from .models import Course, Subject


@method_decorator(never_cache, name='dispatch')
class ExploreView(ListView):
    template_name = 'courses/course/explore.html'
    context_object_name = 'courses'
    paginate_by = 12

    def get_queryset(self):
        self.query = self.request.GET.get('q', '').strip()[:200]
        self.subject_slug = self.request.GET.get('subject', '').strip()
        self.order = self.request.GET.get('sort', 'newest')
        ordering = {'newest': ('-created', '-pk'), 'oldest': ('created', 'pk'), 'title': ('title', 'pk')}
        if self.order not in ordering:
            self.order = 'newest'
        qs = Course.objects.filter(status='published').select_related('owner', 'subject').annotate(total_modules=Count('modules'), teacher_name=Concat('owner__first_name', Value(' '), 'owner__last_name'))
        if self.query:
            qs = qs.filter(Q(title__icontains=self.query) | Q(overview__icontains=self.query) | Q(owner__first_name__icontains=self.query) | Q(owner__last_name__icontains=self.query) | Q(owner__username__icontains=self.query) | Q(teacher_name__icontains=self.query))
        self.selected_subject = None
        if self.subject_slug:
            self.selected_subject = get_object_or_404(Subject, slug=self.subject_slug)
            qs = qs.filter(subject=self.selected_subject)
        from students.favorites import with_favorites
        return with_favorites(qs.order_by(*ordering[self.order]), self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop('page', None)
        context.update(query=self.query, sort=self.order, selected_subject=self.selected_subject,
                       subjects=Subject.objects.annotate(total_courses=Count('courses', filter=Q(courses__status='published'))),
                       pagination_query=params.urlencode())
        return context


def subject_redirect(request, subject):
    get_object_or_404(Subject, slug=subject)
    params = request.GET.copy()
    params['subject'] = subject
    return redirect(reverse('course_list') + '?' + params.urlencode())
