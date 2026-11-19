import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('students', '0003_teacherapplication'),
        ('courses', '0015_arabic_content_labels'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ContentCompletion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('completed_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='تاريخ الإكمال')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='content_completions', to=settings.AUTH_USER_MODEL, verbose_name='الطالب')),
                ('content', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='student_completions', to='courses.content', verbose_name='عنصر المحتوى')),
            ],
            options={
                'verbose_name': 'إكمال محتوى',
                'verbose_name_plural': 'إكمال المحتويات',
                'constraints': [models.UniqueConstraint(fields=('student', 'content'), name='unique_student_content_completion')],
            },
        ),
        migrations.CreateModel(
            name='CourseResume',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('last_visited_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='وقت آخر زيارة')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='course_resumes', to=settings.AUTH_USER_MODEL, verbose_name='الطالب')),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='student_resumes', to='courses.course', verbose_name='الدورة')),
                ('last_content', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='resume_positions', to='courses.content', verbose_name='آخر عنصر محتوى')),
            ],
            options={
                'verbose_name': 'موضع استئناف التعلّم',
                'verbose_name_plural': 'مواضع استئناف التعلّم',
                'constraints': [models.UniqueConstraint(fields=('student', 'course'), name='unique_student_course_resume')],
            },
        ),
    ]
