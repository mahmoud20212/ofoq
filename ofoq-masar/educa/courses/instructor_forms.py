from pathlib import Path
from urllib.parse import urlparse
from django import forms
from django.core.files.uploadedfile import UploadedFile
from .models import CourseRevision, RevisionModule, RevisionContent
from .revision_requirements import NO_EXPERIENCE, REQUIRED_DETAILS, details_errors


class TeacherUploadWidget(forms.ClearableFileInput):
    template_name = 'instructor/upload-widget.html'

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['widget']['required'] = self.is_required
        return context


class TeacherModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('label_suffix', '')
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if field.help_text:
                field.help_text = field.help_text.rstrip('. ')


class RevisionForm(TeacherModelForm):
    no_experience = forms.BooleanField(required=False, label=NO_EXPERIENCE,
        widget=forms.CheckboxInput(attrs={'data-no-experience': ''}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['subject'].empty_label = 'اختر مجال التعلّم'
        self.fields['cover'].widget = TeacherUploadWidget(attrs={'accept': 'image/*', 'data-image-upload': ''})
        for name in REQUIRED_DETAILS:
            self.fields[name].required = True
            self.fields[name].widget.is_required = True
        self.initial['no_experience'] = self.instance.requirements == NO_EXPERIENCE
        if self.is_bound and self.data.get('no_experience'):
            self.fields['requirements'].required = False

    class Meta:
        model = CourseRevision
        fields = ['subject', 'title', 'short_description', 'overview', 'cover', 'learning_outcomes', 'requirements', 'target_audience', 'is_paid', 'price']
        labels = {'subject': 'مجال التعلّم'}
        widgets = {name: forms.Textarea(attrs={'rows': 3}) for name in ['overview', 'learning_outcomes', 'requirements', 'target_audience']}
        widgets['short_description'] = forms.Textarea(attrs={'rows': 2})
        widgets['price'] = forms.NumberInput(attrs={'min': '0.01', 'step': '0.01', 'data-price': '', 'inputmode': 'decimal', 'dir': 'ltr', 'placeholder': '0.00'})
        widgets['is_paid'] = forms.CheckboxInput(attrs={'data-paid': '', 'role': 'switch', 'aria-labelledby': 'teacher-pricing-title', 'aria-describedby': 'teacher-pricing-status', 'aria-controls': 'teacher-pricing-price'})
        help_texts = {name: 'كل عنصر في سطر مستقل.' for name in ['learning_outcomes', 'requirements', 'target_audience']}

    def clean(self):
        data = super().clean()
        if data.get('no_experience'):
            data['requirements'] = NO_EXPERIENCE
        for name, error in details_errors(data).items():
            if name not in self.errors:
                self.add_error(name, error)
        if not data.get('is_paid'):
            self._errors.pop('price', None)
            data['price'] = None
        cover = data.get('cover')
        if isinstance(cover, UploadedFile) and cover.size > 10 * 1024 * 1024:
            self.add_error('cover', 'حجم الغلاف الأقصى 10 ميغابايت.')
        return data


class UnitForm(TeacherModelForm):
    class Meta:
        model = RevisionModule
        fields = ['title', 'description']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}


class LessonForm(TeacherModelForm):
    class Meta:
        model = RevisionContent
        fields = ['kind', 'title', 'text', 'url', 'file', 'is_preview']
        labels = {'title': 'عنوان المحتوى', 'text': 'المحتوى النصي', 'file': 'ملف المحتوى'}
        widgets = {'text': forms.Textarea(attrs={'rows': 8}), 'kind': forms.Select(attrs={'data-lesson-kind': ''})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        kind = self.data.get('kind') or self.initial.get('kind') or self.instance.kind
        if self.instance.pk:
            self.fields['kind'].disabled = True
            kind = self.instance.kind
        if kind == 'image':
            self.fields['file'] = forms.ImageField(label='الصورة', required=False, widget=TeacherUploadWidget(attrs={'accept': 'image/*', 'data-image-upload': ''}))
        else:
            self.fields['file'].widget = TeacherUploadWidget()

    def clean(self):
        data = super().clean()
        kind = data.get('kind')
        if kind == 'text' and not (data.get('text') or '').strip():
            self.add_error('text', 'أدخل نص المحتوى')
        if kind == 'video':
            url = data.get('url') or ''
            host = (urlparse(url).hostname or '').lower()
            if host not in ['youtube.com', 'www.youtube.com', 'youtu.be', 'vimeo.com', 'www.vimeo.com']:
                self.add_error('url', 'استخدم رابط فيديو من YouTube أو Vimeo.')
        asset = data.get('file')
        if kind in ['image', 'file'] and not asset:
            self.add_error('file', 'اختر ملف المحتوى')
        if isinstance(asset, UploadedFile) and asset.size > 25 * 1024 * 1024:
            self.add_error('file', 'حجم الملف الأقصى 25 ميغابايت.')
        if kind == 'file' and asset and Path(asset.name).suffix.lower() not in ['.pdf', '.txt', '.zip', '.py', '.ipynb', '.csv', '.json', '.docx', '.pptx', '.xlsx']:
            self.add_error('file', 'نوع الملف غير مدعوم. استخدم PDF أو ملف تدريب أو مستندًا.')
        if kind != 'text': data['text'] = ''
        if kind != 'video': data['url'] = ''
        if kind not in ['image', 'file']: data['file'] = ''
        return data
