from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory

from .assessment_models import AssessmentVersion, AssessmentQuestion, AssessmentOption
from .instructor_forms import TeacherModelForm


class AssessmentSettingsForm(TeacherModelForm):
    class Meta:
        model = AssessmentVersion
        fields = ['title', 'module', 'instructions', 'pass_percentage', 'max_attempts']
        widgets = {'instructions': forms.Textarea(attrs={'rows': 3}),
            'pass_percentage': forms.NumberInput(attrs={'step': '.01', 'min': 0, 'max': 100}),
            'max_attempts': forms.NumberInput(attrs={'min': 1})}

    def __init__(self, *args, revision, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.course_revision = revision
        self.fields['module'].queryset = revision.modules.all()
        self.fields['module'].empty_label = 'الدورة كاملة'


class AssessmentQuestionForm(TeacherModelForm):
    def __init__(self, *args, require_complete=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['text'].required = require_complete
        self.fields['text'].error_messages['required'] = 'اكتب نص السؤال'

    class Meta:
        model = AssessmentQuestion
        fields = ['text', 'points']
        widgets = {'text': forms.Textarea(attrs={'rows': 3}),
            'points': forms.NumberInput(attrs={'step': '.01', 'min': '.01'})}


class AssessmentOptionForm(TeacherModelForm):
    class Meta:
        model = AssessmentOption
        fields = ['text', 'order']
        widgets = {'text': forms.TextInput(attrs={'placeholder': 'اكتب نص الخيار', 'autocomplete': 'off'}),
            'order': forms.NumberInput(attrs={'min': 0, 'class': 'assessment-option-order'})}


class AssessmentOptionFormSet(BaseInlineFormSet):
    """Authoring saves complete questions; adding an unsaved row may be incomplete."""
    def __init__(self, *args, require_complete=True, **kwargs):
        self.require_complete = require_complete
        super().__init__(*args, **kwargs)
        selected = self.data.get('correct_option', '') if self.is_bound else ''
        for form in self.forms:
            if form.prefix == selected:
                form.empty_permitted = False

    def clean(self):
        super().clean()
        allowed = set(self.instance.options.values_list('pk', flat=True)) if self.instance.pk else set()
        seen = set()
        for form in self.forms:
            # Do not let inline formset IDs attach or delete another question's option.
            raw_id = form.data.get(form.add_prefix('id')) if form.is_bound else None
            if raw_id:
                try:
                    pk = int(raw_id)
                except (TypeError, ValueError):
                    raise ValidationError('معرّف خيار غير صالح')
                if pk not in allowed or pk in seen:
                    raise ValidationError('خيار مكرر أو لا يتبع هذا السؤال')
                seen.add(pk)
        value = self.data.get('correct_option', '') if self.is_bound else ''
        self.correct_prefix = value
        if value and not any(form.prefix == value and not form.cleaned_data.get('DELETE')
                for form in self.forms if hasattr(form, 'cleaned_data')):
            raise ValidationError('اختر إجابة صحيحة من خيارات هذا السؤال')
        if not self.require_complete:
            return
        active = []
        for form in self.forms:
            row = getattr(form, 'cleaned_data', {})
            if row.get('DELETE'):
                continue
            text = row.get('text', '').strip()
            if form.instance.pk or text or form.prefix == value:
                active.append(form)
                if not text:
                    form.add_error('text', 'اكتب نص الخيار أو احذفه')
        errors = []
        if sum(bool(form.cleaned_data.get('text', '').strip()) for form in active) < 2:
            errors.append('أضف خيارين مكتملين على الأقل')
        if not value:
            errors.append('حدّد إجابة صحيحة واحدة')
        if errors:
            raise ValidationError(errors)


OptionFormSet = inlineformset_factory(AssessmentQuestion, AssessmentOption,
    form=AssessmentOptionForm, formset=AssessmentOptionFormSet,
    fields=['text', 'order'], extra=2, can_delete=True, max_num=100,
    validate_max=True, absolute_max=100)
