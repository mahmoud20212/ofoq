"""Read-only, login-protected challenge summaries; editor comes separately."""
from urllib.parse import urlencode
from django import forms
from django.core.paginator import Paginator
from django.urls import reverse
from courses.lab_discovery import available_general_versions, summary, STATE_LABELS, DIFFICULTY_LABELS
from .views import StudentPageView
from django.conf import settings
from django.http import Http404
from django.core.exceptions import ValidationError
from courses.lab_services import challenge_for_execution
from courses.lab_editor_services import read_code
from courses.judge0 import Judge0Error


class ChallengeFilters(forms.Form):
    q = forms.CharField(label='ابحث عن تحدٍّ', required=False, max_length=200,
        widget=forms.TextInput(attrs={'placeholder':'ابحث بالعنوان','type':'search'}))
    language = forms.ChoiceField(label='اللغة والإصدار',required=False)
    difficulty = forms.ChoiceField(label='الصعوبة',required=False,
        choices=[('','كل المستويات'),*DIFFICULTY_LABELS.items()])
    tag = forms.ChoiceField(label='الوسم',required=False)
    state = forms.ChoiceField(label='حالة الحل',required=False,
        choices=[('','كل الحالات'),*STATE_LABELS.items()])

    def __init__(self,*args,languages,tags,**kwargs):
        kwargs.setdefault('label_suffix','')
        super().__init__(*args,**kwargs)
        self.fields['language'].choices=[('','كل اللغات'),*[(str(pk),label) for pk,label in languages]]
        self.fields['tag'].choices=[('','كل الوسوم'),*[(tag,tag) for tag in tags]]


class StudentChallengesView(StudentPageView):
    section='challenges'
    template_name='students/dashboard/challenges.html'
    page_size=12

    def get_context_data(self,**kwargs):
        context=super().get_context_data(**kwargs)
        available=available_general_versions(self.request.user)
        facets=list(available.values('pk','tags','language_id','language__name','language__version'))
        languages=sorted({(row['language_id'],f"{row['language__name']} {row['language__version']}") for row in facets},key=lambda pair:pair[1])
        tags=sorted({tag for row in facets for tag in row['tags']})
        names=('q','language','difficulty','tag','state')
        data={name:self.request.GET.get(name,'') for name in names}
        form=ChallengeFilters(data,languages=languages,tags=tags)
        filtered=available
        if form.is_valid():
            filters=form.cleaned_data
            if filters['q']:filtered=filtered.filter(title__icontains=filters['q'])
            if filters['language']:filtered=filtered.filter(language_id=int(filters['language']))
            if filters['difficulty']:filtered=filtered.filter(difficulty=filters['difficulty'])
            if filters['state']:filtered=filtered.filter(learning_state=filters['state'])
            if filters['tag']:
                # Exact JSON-array membership, also supported on SQLite (no unsupported contains lookup).
                ids=[row['pk'] for row in facets if filters['tag'] in row['tags']]
                filtered=filtered.filter(pk__in=ids)
        else:
            filtered=filtered.none()
        public=filtered.order_by('-reviewed_at','-pk').values('pk','challenge_id','title','description','difficulty',
            'tags','language__name','language__version','learning_state')
        page=Paginator(public,self.page_size).get_page(self.request.GET.get('page'))
        cards=[summary(row) for row in page.object_list]
        retained={name:value for name,value in data.items() if value}
        def page_url(number):return reverse('student_challenges')+'?'+urlencode({**retained,'page':number})
        context.update(filter_form=form,challenges=cards,page=page,total_available=len(facets),
            filtered_count=page.paginator.count,has_filters=bool(retained),
            previous_url=page_url(page.previous_page_number()) if page.has_previous() else None,
            next_url=page_url(page.next_page_number()) if page.has_next() else None)
        return context


class StudentChallengeSolveView(StudentPageView):
    section='challenges'
    template_name='students/dashboard/challenge-solve.html'

    def get_context_data(self,**kwargs):
        if not settings.LAB_EDITOR_API_ENABLED:
            raise Http404
        context=super().get_context_data(**kwargs)
        try:
            version=challenge_for_execution(self.request.user,self.kwargs['challenge_id'])
        except (ValidationError,Judge0Error):
            raise Http404 from None
        if version.challenge.kind!='general':
            raise Http404
        draft=read_code(self.request.user,version.challenge_id,version.pk)
        examples=list(version.examples.order_by('order','pk').values('id','stdin','expected_output','explanation'))
        language_name = version.language.name.lower()
        file_extension = 'py' if 'python' in language_name else 'js' if 'javascript' in language_name else 'cpp' if 'c++' in language_name or 'cpp' in language_name else 'txt'
        context.update(page_title=version.title,problem={
            'title':version.title,'description':version.description,'input_format':version.input_format,
            'output_format':version.output_format,'constraints':version.constraints_text,'examples':examples},
            editor_config={'draft':draft,'starter_code':version.starter_code,'file_extension':file_extension,'examples':examples,'read_url':reverse('lab_code_read',args=[version.challenge_id,version.pk]),
                'save_url':reverse('lab_code_update',args=[version.challenge_id,version.pk]),
                'run_url':reverse('lab_run_create',args=[version.challenge_id]),
                'submission_url':reverse('lab_submission_create',args=[version.challenge_id]),
                'submission_enabled':settings.LAB_SUBMISSION_API_ENABLED,
                'run_enabled':settings.LAB_RUN_API_ENABLED,'version_uid':str(version.uid),
                'storage_key':f'masar-run:{self.request.user.pk}:{version.uid}',
                'login_url':reverse('sso_login')+'?'+urlencode({'next':self.request.path})})
        return context
