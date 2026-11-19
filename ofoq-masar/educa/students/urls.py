from django.urls import include, path
from courses import sso
from . import views
from .application_views import TeacherApplicationView, TeacherApplicationCVView
from .favorites import update_favorite
from .progress_views import complete_content, uncomplete_content
from .challenges import StudentChallengesView, StudentChallengeSolveView

urlpatterns = [
    path('challenges/', StudentChallengesView.as_view(), name='student_challenges'),
    path('challenges/<int:challenge_id>/solve/', StudentChallengeSolveView.as_view(), name='student_challenge_solve'),
    path('courses/<int:course_id>/assessments/<int:assessment_id>/', include('students.assessment_urls')),
    path('courses/<int:course_id>/content/<int:content_id>/complete/', complete_content, name='student_content_complete'),
    path('courses/<int:course_id>/content/<int:content_id>/incomplete/', uncomplete_content, name='student_content_incomplete'),
    path('teacher-application/', TeacherApplicationView.as_view(), name='student_teacher_application'),
    path('teacher-application/<int:application_id>/cv/', TeacherApplicationCVView.as_view(), name='student_teacher_application_cv'),
    path('register/', sso.start, {'registration': True}, name='student_registration'),
    path('enroll-course/', views.StudentEnrollCourseView.as_view(), name='student_enroll_course'),
    path('dashboard/', views.StudentPageView.as_view(template_name='students/dashboard/home.html'), name='student_dashboard'),
    path('courses/', views.StudentCourseListView.as_view(), name='student_course_list'),
    path('courses/<int:course_id>/', views.StudentCourseOverviewView.as_view(), name='student_course_overview'),
    path('courses/<int:course_id>/modules/', views.StudentCourseUnitsView.as_view(), name='student_course_units'),
    path('courses/<int:course_id>/modules/<int:module_id>/', views.StudentModuleView.as_view(), name='student_module'),
    path('courses/<int:course_id>/learn/', views.StudentLessonView.as_view(), name='student_course_learn'),
    path('courses/<int:course_id>/learn/<int:content_id>/', views.StudentLessonView.as_view(), name='student_lesson'),
    path('favorites/', views.StudentFavoritesView.as_view(), name='student_favorites'),
    path('favorites/<int:course_id>/', update_favorite, name='student_favorite_update'),
    path('purchases/', views.StudentPageView.as_view(section='purchases', template_name='students/dashboard/empty.html'), name='student_purchases'),
    path('notifications/read-all/', views.StudentNotificationReadView.as_view(), name='student_notifications_read_all'),
    path('notifications/<int:notification_id>/read/', views.StudentNotificationReadView.as_view(), name='student_notification_read'),
    path('notifications/', views.StudentNotificationsView.as_view(), name='student_notifications'),
    path('course/<int:pk>/', views.StudentCourseDetailView.as_view(), name='student_course_detail'),
    path('course/<int:pk>/<int:module_id>/', views.StudentCourseDetailView.as_view(), name='student_course_detail_module'),
]
