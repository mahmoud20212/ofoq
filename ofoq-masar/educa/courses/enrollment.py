# Published, explicitly configured free courses can be enrolled without payment.
FREE_DEMO_SLUG = 'free-learning-starter-demo'
DEMO_TEACHER = 'demo_masar_teacher'

def free_demo_courses(queryset):
    return queryset.filter(status='published', pricing_configured=True, is_paid=False)
