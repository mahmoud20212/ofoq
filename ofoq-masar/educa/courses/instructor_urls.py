from django.urls import path
from . import instructor_views as views
from .teacher_profiles import TeacherProfileEditView, PublicTeacherProfileView
from . import feedback
from . import assessment_authoring as assessments
from . import lab_authoring as lab

app_name = 'instructor'
urlpatterns = [
    path('revisions/<int:revision_id>/challenges/', lab.listing, name='challenges'),
    path('revisions/<int:revision_id>/challenges/new/', lab.edit, name='challenge_add'),
    path('revisions/<int:revision_id>/challenges/<int:version_id>/', lab.detail, name='challenge_detail'),
    path('revisions/<int:revision_id>/challenges/<int:version_id>/edit/', lab.edit, name='challenge_edit'),
    path('revisions/<int:revision_id>/challenges/<int:version_id>/preview/', lab.preview, name='challenge_preview'),
    path('revisions/<int:revision_id>/challenges/<int:version_id>/review/', lab.preview, {'private': True}, name='challenge_review'),
    path('revisions/<int:revision_id>/challenges/<int:version_id>/action/', lab.action, name='challenge_action'),
    path('revisions/<int:revision_id>/challenges/<int:version_id>/state/', lab.state, name='challenge_state'),
    path('revisions/<int:revision_id>/assessments/', assessments.AssessmentListView.as_view(), name='assessments'),
    path('revisions/<int:revision_id>/assessments/new/', assessments.AssessmentSettingsView.as_view(), name='assessment_add'),
    path('revisions/<int:revision_id>/assessments/preview/', assessments.AssessmentPreviewView.as_view(), name='assessments_preview'),
    path('revisions/<int:revision_id>/assessments/<int:version_id>/', assessments.AssessmentDetailView.as_view(), name='assessment'),
    path('revisions/<int:revision_id>/assessments/<int:version_id>/edit/', assessments.AssessmentSettingsView.as_view(), name='assessment_edit'),
    path('revisions/<int:revision_id>/assessments/<int:version_id>/preview/', assessments.AssessmentPreviewView.as_view(), name='assessment_preview'),
    path('revisions/<int:revision_id>/assessments/<int:version_id>/review/', assessments.AssessmentPreviewView.as_view(review_answers=True), name='assessment_review'),
    path('revisions/<int:revision_id>/assessments/<int:version_id>/questions/new/', assessments.AssessmentQuestionView.as_view(), name='assessment_question_add'),
    path('revisions/<int:revision_id>/assessments/<int:version_id>/questions/order/', assessments.AssessmentQuestionOrderView.as_view(), name='assessment_question_order'),
    path('revisions/<int:revision_id>/assessments/<int:version_id>/questions/<int:question_id>/edit/', assessments.AssessmentQuestionView.as_view(), name='assessment_question_edit'),
    path('revisions/<int:revision_id>/assessments/<int:version_id>/questions/<int:question_id>/<slug:action>/', assessments.AssessmentStructureView.as_view(), name='assessment_question_action'),
    path('revisions/<int:revision_id>/assessments/<int:version_id>/<slug:action>/', assessments.AssessmentStructureView.as_view(), name='assessment_action'),
    path('courses/<int:course_id>/comments/', feedback.teacher_comments, name='comments'),
    path('courses/<int:course_id>/comments/<int:comment_id>/<slug:action>/', feedback.teacher_comment_action, name='comment_action'),
    path('profile/', TeacherProfileEditView.as_view(), name='profile'),
    path('profile/<int:user_id>/', PublicTeacherProfileView.as_view(), name='public_profile'),
    path('assets/<path:name>', views.revision_asset, name='asset'),
    path('dashboard/', views.TeacherView.as_view(), name='dashboard'),
    path('courses/', views.TeacherCoursesView.as_view(), name='courses'),
    path('courses/new/', views.CourseCreateView.as_view(), name='create'),
    path('courses/<int:course_id>/', views.CourseWorkspaceView.as_view(), name='course'),
    path('courses/<int:course_id>/edit/', views.StartRevisionView.as_view(), name='start'),
    path('courses/<int:course_id>/versions/', views.CourseVersionsView.as_view(), name='versions'),
    path('courses/<int:course_id>/action/<slug:action>/', views.CourseLifecycleView.as_view(), name='lifecycle'),
    path('revisions/<int:revision_id>/', views.RevisionWorkspaceView.as_view(), name='revision'),
    path('revisions/<int:revision_id>/edit/', views.RevisionEditView.as_view(), name='edit'),
    path('revisions/<int:revision_id>/reorder/', views.RevisionReorderView.as_view(), name='reorder'),
    path('revisions/<int:revision_id>/preview/', views.RevisionPreviewView.as_view(), name='preview'),
    path('revisions/<int:revision_id>/versions/<slug:action>/', views.VersionActionView.as_view(), name='version_action'),
    path('revisions/<int:revision_id>/action/<slug:action>/', views.RevisionActionView.as_view(), name='action'),
    path('revisions/<int:revision_id>/modules/new/', views.UnitEditView.as_view(), name='unit_add'),
    path('modules/<int:module_id>/edit/', views.UnitEditView.as_view(), name='unit_edit'),
    path('modules/<int:module_id>/lessons/new/', views.LessonEditView.as_view(), name='lesson_add'),
    path('lessons/<int:lesson_id>/edit/', views.LessonEditView.as_view(), name='lesson_edit'),
    path('revisions/<int:revision_id>/<slug:kind>/<int:object_id>/<slug:action>/', views.StructureActionView.as_view(), name='structure'),
    path('notifications/', views.TeacherNotificationsView.as_view(), name='notifications'),
]
