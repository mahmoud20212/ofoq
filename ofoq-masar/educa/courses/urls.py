from django.urls import path

from . import views
from .details import CourseDetailsView, LessonPreviewView
from .catalog import subject_redirect
from .instructor_legacy import legacy_management
from .instructor_views import CourseCreateView as TeacherCreateView, TeacherCoursesView

urlpatterns = [
    path('<slug:slug>/preview/<int:content_id>/', LessonPreviewView.as_view(), name='lesson_preview'),
    path(
        'mine/',
        TeacherCoursesView.as_view(),
        name='manage_course_list',
    ),
    path(
        'create/',
        TeacherCreateView.as_view(),
        name='course_create',
    ),
    path(
        '<pk>/edit/',
        legacy_management,
        name='course_edit',
    ),
    path(
        '<pk>/delete/',
        legacy_management,
        name='course_delete',
    ),
    path(
        '<pk>/module/',
        legacy_management,
        name='course_module_update',
    ),
    path(
        'module/<int:module_id>/content/<model_name>/create/',
        legacy_management,
        name='module_content_create',
    ),
    path(
        'module/<int:module_id>/content/<model_name>/<id>/',
        legacy_management,
        name='module_content_update',
    ),
    path(
        'content/<int:id>/delete/',
        legacy_management,
        name='module_content_delete',
    ),
    path(
        'module/<int:module_id>/',
        legacy_management,
        name='module_content_list',
    ),
    path(
        'module/order/',
        legacy_management,
        name='module_order',
    ),
    path(
        'content/order/',
        legacy_management,
        name='content_order',
    ),
    path(
        'subject/<slug:subject>/',
        subject_redirect,
        name='course_list_subject',
    ),
    path(
        '<slug:slug>/',
        CourseDetailsView.as_view(),
        name='course_detail',
    ),
]
