from urllib.parse import urlsplit
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import ListView
from .models import TeacherProfile, Course
from .instructor_forms import TeacherModelForm, TeacherUploadWidget
from .instructor_services import is_teacher
from .instructor_views import TeacherView


class ProfilePhotoWidget(TeacherUploadWidget):
    template_name = 'instructor/profile-photo-widget.html'


class TeacherProfileForm(TeacherModelForm):
    headline = forms.CharField(label='المسمّى المهني', min_length=5, max_length=160,
        help_text='5 أحرف على الأقل', widget=forms.TextInput(attrs={'minlength': 5}),
        error_messages={'required': 'أدخل المسمّى المهني', 'min_length': 'المسمّى المهني يجب أن يتكوّن من 5 أحرف على الأقل'})
    bio = forms.CharField(label='النبذة المهنية', min_length=50, max_length=5000,
        help_text='50 حرفًا على الأقل للتعريف بخبرتك وأسلوبك في التعليم',
        widget=forms.Textarea(attrs={'rows': 6, 'minlength': 50}),
        error_messages={'required': 'أدخل نبذة مهنية عنك', 'min_length': 'النبذة المهنية يجب أن تتكوّن من 50 حرفًا على الأقل'})

    class Meta:
        model = TeacherProfile
        fields = ['photo', 'headline', 'bio', 'expertise', 'linkedin', 'github', 'website']
        widgets = {
            'photo': ProfilePhotoWidget(attrs={'accept': 'image/jpeg,image/png,image/webp', 'data-image-upload': ''}),
            'bio': forms.Textarea(attrs={'rows': 6}),
            'expertise': forms.Textarea(attrs={'rows': 3}),
        }
        help_texts = {'photo': 'JPEG أو PNG أو WebP، حتى 5 ميغابايت', 'expertise': 'كل مجال في سطر مستقل'}

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if isinstance(photo, UploadedFile):
            if photo.size > 5 * 1024 * 1024:
                raise ValidationError('حجم الصورة الأقصى 5 ميغابايت')
            if getattr(photo, 'image', None) is None or photo.image.format not in {'JPEG', 'PNG', 'WEBP'}:
                raise ValidationError('استخدم صورة JPEG أو PNG أو WebP صالحة')
        return photo

    def clean(self):
        data = super().clean()
        for name in ['linkedin', 'github', 'website']:
            value = data.get(name)
            if not value:
                continue
            parts = urlsplit(value)
            host = (parts.hostname or '').lower()
            expected = {'linkedin': 'linkedin.com', 'github': 'github.com'}.get(name)
            if parts.scheme not in {'http', 'https'} or parts.username or parts.password:
                self.add_error(name, 'أدخل رابط HTTP أو HTTPS صالحًا دون بيانات دخول')
            elif expected and host != expected and not host.endswith('.' + expected):
                self.add_error(name, 'أدخل رابطًا من ' + expected)
        return data


class TeacherProfileEditView(TeacherView):
    template_name = 'instructor/profile.html'
    page_title = 'ملفي المهني'
    section = 'profile'

    def profile(self):
        return TeacherProfile.objects.filter(user=self.request.user).first() or TeacherProfile(user=self.request.user)

    def get(self, request):
        return self.render_to_response(self.get_context_data(form=TeacherProfileForm(instance=self.profile()), mark_required=True))

    def post(self, request):
        form = TeacherProfileForm(request.POST, request.FILES, instance=self.profile())
        if form.is_valid():
            form.save()
            messages.success(request, 'تم حفظ ملفك المهني')
            return redirect('instructor:profile')
        return self.render_to_response(self.get_context_data(form=form, mark_required=True))


class PublicTeacherProfileView(ListView):
    template_name = 'courses/teacher-public-profile.html'
    context_object_name = 'teacher_courses'
    paginate_by = 12

    def get_queryset(self):
        self.teacher = get_object_or_404(get_user_model(), pk=self.kwargs['user_id'], is_active=True)
        courses = Course.objects.filter(owner=self.teacher, status='published')
        if not is_teacher(self.teacher) and not courses.exists():
            raise Http404
        return courses.select_related('owner', 'subject').annotate(total_modules=Count('modules')).order_by('-created', '-pk')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(teacher=self.teacher, profile=TeacherProfile.objects.filter(user=self.teacher).first(), teacher_name=self.teacher.get_full_name() or self.teacher.username)
        return context
