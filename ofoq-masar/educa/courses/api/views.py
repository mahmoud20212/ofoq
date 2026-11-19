# from django.shortcuts import get_object_or_404
from django.db.models import Count, Q
from rest_framework import viewsets
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from courses.api.pagination import StandardPagination
from courses.api.permissions import IsEnrolled
from courses.api.serializers import (
    CourseSerializer,
    CourseWithContentsSerializer,
    SubjectSerializer,
)
from courses.models import Course, Subject


class SubjectViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Subject.objects.annotate(total_courses=Count('courses', filter=Q(courses__status='published')))
    serializer_class = SubjectSerializer
    pagination_class = StandardPagination


class CourseViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Course.objects.filter(status='published').prefetch_related('modules')
    serializer_class = CourseSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        if self.action == 'contents':
            return Course.objects.filter(status__in=['published', 'archived']).prefetch_related('modules')
        return super().get_queryset()

    @action(
        detail=True,
        methods=['post'],
        authentication_classes=[BasicAuthentication],
        permission_classes=[IsAuthenticated],
    )
    def enroll(self, request, *args, **kwargs):
        course = self.get_object()
        from courses.enrollment import free_demo_courses
        if not free_demo_courses(Course.objects.filter(pk=course.pk)).exists():
            return Response({'detail': 'هذه الدورة غير متاحة للالتحاق المجاني.'}, status=403)
        course.students.add(request.user)
        return Response({'enrolled': True})

    @action(
        detail=True,
        methods=['get'],
        serializer_class=CourseWithContentsSerializer,
        authentication_classes=[BasicAuthentication],
        permission_classes=[IsAuthenticated, IsEnrolled],
    )
    def contents(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)
