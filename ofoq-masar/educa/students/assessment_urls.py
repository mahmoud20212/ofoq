from django.urls import path
from . import assessment_views as views
from . import assessment_pages as pages

urlpatterns = [
    path('', pages.introduction, name='student_assessment_page'),
    path('begin/', pages.begin, name='student_assessment_begin'),
    path('history/', pages.history_page, name='student_assessment_history_page'),
    path('attempts/<int:attempt_id>/solve/', pages.solve, name='student_assessment_solve'),
    path('attempts/<int:attempt_id>/summary/', pages.result_page, name='student_assessment_result_page'),
    path('start/', views.start, name='student_assessment_start'),
    path('attempts/', views.history, name='student_assessment_history'),
    path('attempts/<int:attempt_id>/', views.read, name='student_assessment_attempt'),
    path('attempts/<int:attempt_id>/answers/', views.save, name='student_assessment_answers'),
    path('attempts/<int:attempt_id>/submit/', views.submit, name='student_assessment_submit'),
    path('attempts/<int:attempt_id>/result/', views.result, name='student_assessment_result'),
]
