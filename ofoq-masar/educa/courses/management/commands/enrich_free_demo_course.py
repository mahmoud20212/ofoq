from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max

from courses.enrollment import FREE_DEMO_SLUG, DEMO_TEACHER
from courses.models import Course, Module, Content, Text, Video, Image, File


class Command(BaseCommand):
    help = 'Add varied content only to the requested free demo, without replacing existing lessons.'

    @transaction.atomic
    def handle(self, *args, **options):
        course = Course.objects.filter(slug=FREE_DEMO_SLUG, owner__username=DEMO_TEACHER).select_related('owner').first()
        if course is None:
            raise CommandError('Create the free demo course first; no other courses will be modified.')
        assets = Path(__file__).resolve().parents[2] / 'demo_assets'
        definitions = [
            ('شاهد وافهم', 'تعرّف على بايثون من خلال فيديو عربي ورسم يوضّح فكرة المتغيّرات.', [
                (Video, 'مقدمة بايثون بالعربية — أكاديمية الزيرو', {'url': 'https://www.youtube.com/watch?v=mvZHDpCHphk'}, None),
                (Image, 'المتغيّر: اسم ثابت وقيمة تتغيّر', {}, 'variables.svg'),
            ]),
            ('تطبيقات ومراجعة', 'طبّق ما تعلّمته، ثم راجع إجاباتك باستخدام ملف التدريب.', [
                (Text, 'تطبيق عملي: حساب تكلفة الطلب', {'content': 'سنحسب تكلفة طلب بسيط باستخدام متغيّرات واضحة.\n\nالخطوة الأولى: حدّد السعر والكمية.\nprice = 20\nquantity = 3\n\nالخطوة الثانية: احسب المجموع.\ntotal = price * quantity\nprint(total)\n\nالناتج هو 60. غيّر الكمية إلى 5 وتوقّع الناتج قبل تشغيل المثال.\n\nهذا تمرين للتجربة الذاتية؛ لا يوجد تشغيل كود أو حفظ للإجابة داخل المنصة حاليًا.'}, None),
                (File, 'ورقة تدريب: المتغيّرات والعمليات الحسابية', {}, 'python-practice.txt'),
                (Text, 'راجع فهمك', {'content': 'حاول الإجابة قبل قراءة الحلول في الأسفل.\n\n1. ما الفرق بين اسم المتغيّر وقيمته؟\n2. إذا كانت price = 20 وquantity = 5، فما قيمة price * quantity؟\n3. كيف تطبع قيمة المتغيّر total؟\n\nإجابات للمراجعة\n1. الاسم يشير إلى القيمة التي نستخدمها، ويمكن إسناد قيمة جديدة إلى الاسم نفسه.\n2. الناتج 100.\n3. نكتب print(total).\n\nهذه مراجعة ذاتية تجريبية، وليست اختبارًا بدرجات.'}, None),
            ]),
        ]
        added = 0
        for title, description, lessons in definitions:
            module = course.modules.filter(title=title).first()
            if module is None:
                last = course.modules.aggregate(value=Max('order'))['value']
                module = Module.objects.create(course=course, title=title, description=description, order=0 if last is None else last + 1)
            for model, lesson_title, fields, asset in lessons:
                if any(content.item and content.item.title == lesson_title for content in module.contents.prefetch_related('item')):
                    continue
                item = model(owner=course.owner, title=lesson_title, **fields)
                if asset:
                    item.file.save('masar-demo-' + asset, ContentFile((assets / asset).read_bytes()), save=False)
                item.save()
                last = module.contents.aggregate(value=Max('order'))['value']
                Content.objects.create(module=module, item=item, order=0 if last is None else last + 1, is_preview=False)
                added += 1
        self.stdout.write(f'Added {added} lessons to the free demo only. Existing lessons and enrollments preserved.')
