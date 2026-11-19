from django import forms

from courses.models import Course
from courses.enrollment import free_demo_courses


class CourseEnrollForm(forms.Form):
    course = forms.ModelChoiceField(
        queryset=Course.objects.none(),
        widget=forms.HiddenInput
    )

    def __init__(self, *args, **kwargs):
        super(CourseEnrollForm, self).__init__(*args, **kwargs)
        self.fields['course'].queryset = free_demo_courses(Course.objects.all())


from django.core.validators import URLValidator
from .application_files import validate_cv


class TeacherApplicationForm(forms.Form):
    specialty = forms.CharField(label='التخصص', max_length=200)
    experience = forms.CharField(label='نبذة عن الخبرة', max_length=3000, widget=forms.Textarea(attrs={'rows': 5}))
    topics = forms.CharField(label='موضوعات الدورات المقترحة', max_length=3000, widget=forms.Textarea(attrs={'rows': 5}))
    portfolio = forms.URLField(label='رابط معرض الأعمال (اختياري)', required=False, max_length=500, validators=[URLValidator(schemes=['http', 'https'])])
    cv = forms.FileField(label='السيرة الذاتية', validators=[validate_cv], widget=forms.FileInput(attrs={'accept': '.pdf,.docx'}), help_text='PDF أو DOCX، بحد أقصى 5 ميغابايت.')

    def __init__(self, *args, previous=None, **kwargs):
        super().__init__(*args, **kwargs)
        if previous:
            self.fields['cv'].required = False
            self.fields['cv'].help_text += ' اترك الحقل فارغًا للاحتفاظ بالسيرة السابقة.'
