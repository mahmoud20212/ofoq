from django.urls import path
from . import feedback

urlpatterns = [
    path('courses/<int:course_id>/reviews/<slug:action>/', feedback.review_action, name='course_review_action'),
    path('courses/<int:course_id>/contents/<int:content_id>/comments/<slug:action>/', feedback.comment_action, name='lesson_comment_create'),
    path('courses/<int:course_id>/contents/<int:content_id>/comments/<int:comment_id>/<slug:action>/', feedback.comment_action, name='lesson_comment_action'),
]
