"""Authoring inputs only; publication/readiness stays in lifecycle services."""
from django import forms
from decimal import Decimal
from django.forms import formset_factory
from .lab_models import ChallengeVersion, ProgrammingLanguage, MAX_SOURCE_CHARS
from .lab_policy import resource_limits


class ChallengeForm(forms.Form):
    title = forms.CharField(label='عنوان التحدي', required=False, max_length=250)
    module_id = forms.ModelChoiceField(label='نطاق التحدي', queryset=None, required=False, empty_label='الدورة كاملة')
    description = forms.CharField(label='وصف التحدي', required=False, widget=forms.Textarea(attrs={'rows':4}))
    difficulty = forms.ChoiceField(label='الصعوبة', choices=ChallengeVersion.DIFFICULTIES)
    tags = forms.CharField(label='الوسوم', required=False, help_text='وسم واحد في كل سطر', widget=forms.Textarea(attrs={'rows':2}))
    language_id = forms.ModelChoiceField(label='اللغة والإصدار', queryset=None, required=False, empty_label='اختر إصدارًا مختبرًا')
    input_format = forms.CharField(label='تنسيق المدخلات', required=False, widget=forms.Textarea(attrs={'rows':2}))
    output_format = forms.CharField(label='تنسيق المخرجات', required=False, widget=forms.Textarea(attrs={'rows':2}))
    constraints_text = forms.CharField(label='قيود المسألة', required=False, widget=forms.Textarea(attrs={'rows':2}))
    starter_code = forms.CharField(label='كود البداية', required=False, strip=False, max_length=MAX_SOURCE_CHARS, widget=forms.Textarea(attrs={'rows':6,'dir':'ltr','spellcheck':'false'}))
    reference_solution = forms.CharField(label='الحل المرجعي الخاص', required=False, strip=False, max_length=MAX_SOURCE_CHARS, widget=forms.Textarea(attrs={'rows':8,'dir':'ltr','spellcheck':'false'}))
    cpu_seconds = forms.DecimalField(label='وقت المعالج بالثواني', min_value=Decimal('.01'), decimal_places=2)
    memory_kb = forms.IntegerField(label='الذاكرة KiB', min_value=1)
    output_bytes = forms.IntegerField(label='المخرجات بالبايت', min_value=1)
    comparison = forms.ChoiceField(label='مقارنة المخرجات', choices=ChallengeVersion.COMPARISONS)
    required_for_completion = forms.BooleanField(label='مطلوب لإتمام الدورة', required=False)

    def __init__(self, *args, version=None, revision=None, **kwargs):
        self.version, self.revision = version, revision
        kwargs.setdefault('label_suffix','')
        initial = kwargs.setdefault('initial', {})
        policy = resource_limits()
        initial.update(difficulty='easy', comparison='exact', **{k:policy[k] for k in ('cpu_seconds','memory_kb','output_bytes')})
        if version:
            for name in self.base_fields:
                initial[name] = getattr(version, name, None)
            initial['tags'] = '\n'.join(version.tags)
        super().__init__(*args, **kwargs)
        languages = ProgrammingLanguage.objects.filter(active=True, verified_at__isnull=False,
            engine__active=True, engine__verified_at__isnull=False).select_related('engine')
        # Reject stale catalog/profile mappings too, not merely an active flag.
        available = []
        from .judge0 import execution_profile_hash, Judge0Error
        for language in languages:
            try:
                if (language.tested_profile_hash == execution_profile_hash(language.engine)
                        and language.engine.discovered_languages.filter(remote_id=language.judge0_language_id,
                            display_name=language.remote_name, present=True).exists()):
                    available.append(language.pk)
            except Judge0Error:
                pass
        self.fields['language_id'].queryset = ProgrammingLanguage.objects.filter(pk__in=available)
        if version and version.language_id:
            self.fields['language_id'].disabled = True
            self.fields['language_id'].queryset = ProgrammingLanguage.objects.filter(pk=version.language_id)
            self.fields['language_id'].help_text = 'اللغة مثبتة لهذه النسخة؛ تغييرها يحتاج نسخة جديدة'
        if revision:
            self.fields['module_id'].queryset = revision.modules.all()
        else:
            del self.fields['module_id']; del self.fields['required_for_completion']
        for name in ('cpu_seconds','memory_kb','output_bytes'):
            self.fields[name].max_value = policy['max_'+name]
            self.fields[name].widget.attrs['max'] = str(policy['max_'+name])
        for field in self.fields.values():
            field.widget.attrs.setdefault('class','lab-input')

    def clean_tags(self):
        tags = [line.strip() for line in self.cleaned_data['tags'].splitlines() if line.strip()]
        if any(len(tag)>60 for tag in tags):
            raise forms.ValidationError('الوسم حتى 60 حرفًا')
        return tags

    def clean(self):
        data = super().clean()
        for key in ('cpu_seconds','memory_kb','output_bytes'):
            if key in data and data[key]>resource_limits()['max_'+key]:
                self.add_error(key,'يتجاوز سقف المنصة المسموح')
        return data

    def changes(self):
        return {key: (value.pk if key in ('module_id','language_id') and value else value)
                for key,value in self.cleaned_data.items()}


class ExampleForm(forms.Form):
    stdin = forms.CharField(label='المدخلات', required=False, strip=False, widget=forms.Textarea(attrs={'rows':2,'dir':'ltr'}))
    expected_output = forms.CharField(label='المخرجات المتوقعة', required=False, strip=False, widget=forms.Textarea(attrs={'rows':2,'dir':'ltr'}))
    explanation = forms.CharField(label='شرح المثال', required=False, widget=forms.Textarea(attrs={'rows':2}))


class TestCaseForm(ExampleForm):
    explanation = None
    visible = forms.BooleanField(label='حالة ظاهرة للطالب', required=False)


Examples = formset_factory(ExampleForm, extra=0, can_delete=True, can_order=True, max_num=100, validate_max=True, absolute_max=101)
TestCases = formset_factory(TestCaseForm, extra=0, can_delete=True, can_order=True, max_num=200, validate_max=True, absolute_max=201)
