from courses.instructor_services import is_teacher


def teacher_application_navigation(request):
    if not request.user.is_authenticated:
        return {}
    teacher = is_teacher(request.user)
    return {'application_nav_teacher': teacher, 'application_nav_submitted': not teacher and request.user.teacher_applications.exists()}
