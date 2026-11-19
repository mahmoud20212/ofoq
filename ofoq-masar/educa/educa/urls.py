from courses import sso
from courses.teacher import DemoTeacherView
from courses.catalog import ExploreView
from courses import cart as cart_views
from courses import lab_run_views
from courses import lab_submission_views
from courses import lab_editor_views
"""
URL configuration for educa project.

The `urlpatterns` list routes URLs to views. For more information
please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include,
        path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from courses.views import CourseListView
from courses.landing import LandingPageView
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path('lab/challenges/<int:challenge_id>/versions/<int:version_id>/code/', lab_editor_views.code_read, name='lab_code_read'),
    path('lab/challenges/<int:challenge_id>/versions/<int:version_id>/code/save/', lab_editor_views.code_update, name='lab_code_update'),
    path('lab/challenges/<int:challenge_id>/submission-history/', lab_editor_views.history, name='lab_submission_history'),
    path('lab/submissions/<int:submission_id>/code/', lab_editor_views.source, name='lab_submission_code'),
    path('lab/challenges/<int:challenge_id>/submissions/',lab_submission_views.submission_create,name='lab_submission_create'),
    path('lab/submissions/<int:submission_id>/',lab_submission_views.submission_status,name='lab_submission_status'),
    path('lab/challenges/<int:challenge_id>/runs/', lab_run_views.run_create, name='lab_run_create'),
    path('lab/runs/<int:run_id>/', lab_run_views.run_status, name='lab_run_status'),
    path('feedback/', include('courses.feedback_urls')),
    path('auth/login/', sso.start, name='sso_login'),
    path('auth/register/', sso.start, {'registration': True}, name='sso_register'),
    path('auth/callback/', sso.callback, name='sso_callback'),
    path('auth/logout/', sso.logout, name='sso_logout'),
    path('auth/account/', sso.account, name='sso_account'),
    path('auth/backchannel-logout/', sso.backchannel_logout, name='sso_backchannel'),
    path('teachers/demo-masar-teacher/', DemoTeacherView.as_view(), name='demo_teacher_profile'),
    path('teachers/', include('courses.instructor_urls', namespace='instructor')),
    path(
        'accounts/login/', sso.start, name='login'
    ),
    path(
        'accounts/logout/',
        sso.logout,
        name='logout',
    ),
    path('admin/', admin.site.urls),
    path('course/', include('courses.urls')),
    path('', LandingPageView.as_view(), name='landing'),
    path('courses/', ExploreView.as_view(), name='course_list'),
    path('cart/', cart_views.cart_detail, name='cart_detail'),
    path('cart/add/<int:course_id>/', cart_views.cart_add, name='cart_add'),
    path('cart/remove/<int:course_id>/', cart_views.cart_remove, name='cart_remove'),
    path('students/', include('students.urls')),
    path('api/', include('courses.api.urls', namespace='api')),
    path('chat/', include('chat.urls', namespace='chat')),
    path('__debug__/', include('debug_toolbar.urls')),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL, document_root=settings.MEDIA_ROOT
    )
