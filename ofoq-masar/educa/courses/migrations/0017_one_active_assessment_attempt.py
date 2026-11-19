from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('courses', '0016_assessment_data')]
    operations = [migrations.AddConstraint(
        model_name='assessmentattempt',
        constraint=models.UniqueConstraint(fields=('student', 'assessment'),
            condition=models.Q(status='in_progress'), name='one_active_student_assessment'),
    )]
