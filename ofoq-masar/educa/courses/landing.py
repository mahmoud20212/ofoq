from django.conf import settings
from django.db.models import Count, Q
from django.views.generic import TemplateView

from .models import Course, Subject


class LandingPageView(TemplateView):
    template_name = 'courses/landing.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['featured_courses'] = Course.objects.filter(status='published').select_related(
            'subject', 'owner'
        ).annotate(total_modules=Count('modules'))[:6]
        context['subjects'] = Subject.objects.annotate(
            total_courses=Count('courses', filter=Q(courses__status='published'))
        )[:8]
        context['account_center_url'] = getattr(settings, 'OFOQ_ACCOUNT_CENTER_URL', '')
        context['social_links'] = getattr(settings, 'OFOQ_SOCIAL_LINKS', {})
        return context
