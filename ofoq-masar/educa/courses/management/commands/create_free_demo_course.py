from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.contrib.auth.models import User
from courses.models import Subject, Course, Module, Text, Content
from courses.enrollment import FREE_DEMO_SLUG, DEMO_TEACHER

class Command(BaseCommand):
    help = 'Create the explicitly requested free trial course without enrolling any users.'

    @transaction.atomic
    def handle(self, *args, **options):
        existing = Course.objects.filter(slug=FREE_DEMO_SLUG).first()
        if existing:
            if existing.owner.username != DEMO_TEACHER:
                raise CommandError('The course slug belongs to another teacher; no changes made.')
            self.stdout.write('Free demo already exists; no changes made.')
            return
        teacher, created = User.objects.get_or_create(username=DEMO_TEACHER)
        if created:
            teacher.first_name = 'سامر'
            teacher.last_name = 'الخطيب (تجريبي)'
            teacher.set_unusable_password()
            teacher.save()
        subject, _ = Subject.objects.get_or_create(slug='programming', defaults={'title': 'البرمجة وتطوير الويب'})
        course = Course.objects.create(owner=teacher, subject=subject, slug=FREE_DEMO_SLUG, status='published', is_paid=False, pricing_configured=True,
            title='خطوتك الأولى في البرمجة — دورة مجانية تجريبية',
            short_description='دورة قصيرة مجانية لتجربة الالتحاق والتعلّم داخل أكاديمية أُفُق مَسار.',
            overview='هذه دورة تجريبية مجانية لاختبار رحلة الطالب: الالتحاق، وظهور الدورة في دوراتي، وفتح الدروس والتنقّل بينها. المحتوى تمهيدي ومخصّص للتجربة.',
            learning_outcomes='فهم فكرة البرنامج وتسلسل التعليمات\nالتعرّف على المتغيّرات\nتجربة التنقّل بين دروس الأكاديمية',
            requirements='لا تحتاج إلى خبرة سابقة بالبرمجة', target_audience='المبتدئون ومن يرغبون في تجربة الأكاديمية')
        lessons = [
            ('بداية رحلتك', [('مرحبًا بك في الدورة', 'مرحبًا بك في أكاديمية أُفُق مَسار. هذه دورة مجانية تجريبية.\nبعد الالتحاق ستجدها في دوراتي داخل لوحة الطالب، ويمكنك العودة إلى دروسها في أي وقت.'),
                              ('ما هي البرمجة؟', 'البرمجة هي كتابة تعليمات واضحة ينفّذها الحاسوب.\nمثال: اطلب اسم المستخدم، ثم اعرض رسالة ترحيب باسمه. ترتيب التعليمات يساعدنا على الوصول إلى النتيجة المطلوبة.')]),
            ('فكّر وجرّب', [('تعرّف على المتغيّرات', 'المتغيّر اسم نستخدمه للاحتفاظ بقيمة.\nمثلًا: score = 10\nيمكن تغيير القيمة لاحقًا إلى score = 15.\nجرّب التفكير في اسم متغيّر للاحتفاظ بعدد المحاولات. هذا تمرين للتفكير فقط؛ لا يتم حفظ الإجابات أو التقدّم في هذه المرحلة.')]),
        ]
        for order, (title, rows) in enumerate(lessons):
            module = Module.objects.create(course=course, title=title, order=order)
            for index, (lesson_title, body) in enumerate(rows):
                item = Text.objects.create(owner=teacher, title=lesson_title, content=body)
                Content.objects.create(module=module, item=item, order=index, is_preview=(order == 0 and index == 0))
        self.stdout.write('Created free demo: /course/' + course.slug + '/ (2 modules, 3 lessons; no automatic enrollments).')
