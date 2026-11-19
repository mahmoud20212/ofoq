from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from .models import Course, Content, LessonComment, LessonCommentReply, CourseReview
from .instructor_services import is_teacher


class CommentForm(forms.Form):
    text = forms.CharField(label='التعليق', max_length=2000, widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'شارك سؤالك أو ملاحظتك عن المحتوى…'}), error_messages={'required': 'اكتب تعليقًا قبل الإرسال', 'max_length': 'الحد الأقصى 2000 حرف'})


class ReviewForm(forms.Form):
    rating = forms.TypedChoiceField(label='تقييمك للدورة', coerce=int, choices=[(i, str(i)) for i in range(1, 6)], widget=forms.RadioSelect, error_messages={'required': 'اختر تقييمًا من 1 إلى 5', 'invalid_choice': 'اختر تقييمًا من 1 إلى 5'})
    text = forms.CharField(label='رأيك في الدورة', max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 4, 'placeholder': 'ما الذي استفدت منه؟ وما الذي تقترح تحسينه؟'}))


def accessible_course(user, course_id, teacher_only=False):
    course = get_object_or_404(Course.objects.select_related('owner'), pk=course_id)
    if teacher_only:
        if course.owner_id != user.pk or not is_teacher(user):
            raise Http404
    elif not course.students.filter(pk=user.pk).exists():
        raise Http404
    return course


def review_context(course, user, params):
    visible = course.reviews.filter(is_hidden=False).select_related('author')
    summary = visible.aggregate(total=Count('pk'), average=Avg('rating'))
    counts = dict(visible.order_by().values('rating').annotate(total=Count('pk')).values_list('rating', 'total'))
    mine = course.reviews.filter(author=user).first() if user.is_authenticated else None
    allowed = user.is_authenticated and user.is_active and user.pk != course.owner_id and course.students.filter(pk=user.pk).exists()
    page = Paginator(visible, 10).get_page(params.get('reviews_page'))
    return {
        'review_page': page,
        'own_review_in_page': bool(mine and any(review.pk == mine.pk for review in page)),
        'review_count': summary['total'], 'review_average': summary['average'],
        'review_distribution': [{'stars': i, 'count': counts.get(i, 0), 'percent': round(100 * counts.get(i, 0) / summary['total']) if summary['total'] else 0} for i in range(5, 0, -1)],
        'can_review': allowed, 'own_review': mine,
        'review_form': ReviewForm(initial={'rating': mine.rating, 'text': mine.text} if mine else None),
    }


def comment_context(course, content, user, params):
    comments = LessonComment.objects.filter(course=course, content=content).filter(Q(is_hidden=False) | Q(author=user)).select_related('author', 'reply__author')
    editing = None
    if params.get('edit_comment'):
        editing = get_object_or_404(comments, pk=positive_id(params['edit_comment']), author=user)
    return {'comment_page': Paginator(comments, 20).get_page(params.get('comments_page')), 'editing_comment': editing,
            'comment_form': CommentForm(initial={'text': editing.text} if editing else None)}


def positive_id(value):
    try:
        result = int(value)
        if result <= 0 or result > 9223372036854775807:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise Http404


def confirmation(request, title):
    return render(request, 'feedback/confirm.html', {'confirmation_title': title, 'action_url': request.path})


@never_cache
@login_required
@require_POST
def comment_action(request, course_id, content_id, action, comment_id=None):
    course = accessible_course(request.user, course_id)
    content = get_object_or_404(Content, pk=content_id, module__course=course)
    if content.item is None:
        raise Http404
    comment = get_object_or_404(LessonComment, pk=comment_id, course=course, content=content, author=request.user) if comment_id else None
    target = reverse('student_lesson', args=[course.pk, content.pk]) + '#lesson-comments-title'
    if action == 'delete' and comment:
        if request.POST.get('confirm') != 'yes':
            return confirmation(request, 'حذف التعليق')
        comment.delete()
        messages.success(request, 'تم حذف التعليق')
    elif action == 'save':
        form = CommentForm(request.POST)
        if not form.is_valid():
            from students.views import StudentLessonView
            view = StudentLessonView()
            view.setup(request, course_id=course.pk, content_id=content.pk)
            context = view.get_context_data()
            context.update(comment_form=form, editing_comment=comment)
            return view.render_to_response(context)
        if comment:
            comment.text = form.cleaned_data['text']
            comment.edited_at = timezone.now()
            comment.save(update_fields=['text', 'edited_at'])
        else:
            LessonComment.objects.create(course=course, content=content, author=request.user, **form.cleaned_data)
        messages.success(request, 'تم حفظ التعليق')
    else:
        raise Http404
    return redirect(target)


@never_cache
@login_required
@require_POST
def review_action(request, course_id, action):
    course = accessible_course(request.user, course_id)
    if course.owner_id == request.user.pk:
        raise PermissionDenied('لا يمكنك تقييم دورتك')
    public = request.POST.get('surface') == 'public' and course.status == 'published'
    target = (reverse('course_detail', args=[course.slug]) if public else reverse('student_course_overview', args=[course.pk])) + '#reviews'
    mine = CourseReview.objects.filter(course=course, author=request.user).first()
    if action == 'delete':
        if request.POST.get('confirm') != 'yes':
            return confirmation(request, 'حذف تقييم الدورة')
        if mine:
            mine.delete()
        messages.success(request, 'تم حذف التقييم')
    elif action == 'save':
        form = ReviewForm(request.POST)
        if not form.is_valid():
            if public:
                from .details import CourseDetailsView
                view = CourseDetailsView()
                view.setup(request, slug=course.slug)
                view.object = course
            else:
                from students.views import StudentCourseOverviewView
                view = StudentCourseOverviewView()
                view.setup(request, course_id=course.pk)
            context = view.get_context_data()
            context.update(review_form=form, review_form_invalid=True)
            return view.render_to_response(context)
        with transaction.atomic():
            # Serialize first-time submissions as well as updates for this course.
            Course.objects.select_for_update().get(pk=course.pk)
            review, created = CourseReview.objects.get_or_create(course=course, author=request.user, defaults=form.cleaned_data)
            if not created:
                review.rating = form.cleaned_data['rating']
                review.text = form.cleaned_data['text']
                review.edited_at = timezone.now()
                review.save(update_fields=['rating', 'text', 'edited_at'])
        messages.success(request, 'تم حفظ تقييمك للدورة')
    else:
        raise Http404
    return redirect(target)


@never_cache
@login_required
def teacher_comments(request, course_id):
    if request.method != 'GET':
        return HttpResponseBadRequest()
    course = accessible_course(request.user, course_id, teacher_only=True)
    comments = course.lesson_comments.filter(content__isnull=False, content__module__course=course).select_related('author', 'content__module', 'reply__author')
    state = request.GET.get('state', '')
    selected = request.GET.get('content', '')
    if state in ['visible', 'hidden']:
        comments = comments.filter(is_hidden=state == 'hidden')
    if selected:
        content = get_object_or_404(Content, pk=positive_id(selected), module__course=course)
        comments = comments.filter(content=content)
    page = Paginator(comments, 20).get_page(request.GET.get('page'))
    from .instructor_views import TeacherView
    view = TeacherView()
    view.setup(request)
    view.page_title = 'أسئلة الطلاب'
    view.section = 'courses'
    params = request.GET.copy()
    params.pop('page', None)
    context = view.get_context_data(managed_course=course, comment_page=page, page_obj=page,
        contents=Content.objects.filter(module__course=course).select_related('content_type').prefetch_related('item'), state=state, selected_content=selected, pagination_query=params.urlencode())
    context['breadcrumbs'] = [{'label': 'دوراتي', 'url': reverse('instructor:courses')}, {'label': course.title, 'url': reverse('instructor:course', args=[course.pk])}, {'label': 'أسئلة الطلاب', 'url': None}]
    return render(request, 'instructor/comments.html', context)


@never_cache
@login_required
@require_POST
def teacher_comment_action(request, course_id, comment_id, action):
    course = accessible_course(request.user, course_id, teacher_only=True)
    comment = get_object_or_404(LessonComment, pk=comment_id, course=course, content__isnull=False, content__module__course=course)
    if action in ['hide', 'show', 'delete_reply']:
        title = {'hide': 'إخفاء التعليق', 'show': 'إظهار التعليق', 'delete_reply': 'حذف الرد'}[action]
        if request.POST.get('confirm') != 'yes':
            return confirmation(request, title)
        if action == 'delete_reply':
            LessonCommentReply.objects.filter(comment=comment).delete()
        else:
            comment.is_hidden = action == 'hide'
            if comment.is_hidden:
                comment.hidden_by = request.user
                comment.hidden_at = timezone.now()
            comment.save(update_fields=['is_hidden', 'hidden_by', 'hidden_at'])
    elif action == 'reply':
        form = CommentForm(request.POST)
        if not form.is_valid():
            return render(request, 'instructor/reply-form.html', {'form': form, 'comment': comment, 'managed_course': course, 'page_title': 'رد المعلّم', 'teacher_section': 'courses'})
        with transaction.atomic():
            LessonComment.objects.select_for_update().get(pk=comment.pk)
            reply, created = LessonCommentReply.objects.get_or_create(comment=comment, defaults={'author': request.user, **form.cleaned_data})
            if not created:
                reply.text = form.cleaned_data['text']
                reply.author = request.user
                reply.edited_at = timezone.now()
                reply.save(update_fields=['text', 'author', 'edited_at'])
    else:
        raise Http404
    messages.success(request, 'تم حفظ التغييرات')
    return redirect(reverse('instructor:comments', args=[course.pk]) + '#comment-' + str(comment.pk))
