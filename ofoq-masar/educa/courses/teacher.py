from django.db.models import Count
from django.views.generic import TemplateView
from .models import Course


class DemoTeacherView(TemplateView):
    template_name = 'courses/teacher-profile.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['teacher_courses'] = Course.objects.filter(status='published').filter(
            owner__username='demo_masar_teacher', slug='demo-python-foundations'
        ).select_related('owner', 'subject').annotate(total_modules=Count('modules'))
        return context
