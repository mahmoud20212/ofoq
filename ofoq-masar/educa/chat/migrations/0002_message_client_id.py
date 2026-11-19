from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('chat', '0001_initial')]
    operations = [
        migrations.AddField(model_name='message', name='client_id', field=models.UUIDField(blank=True, null=True)),
        migrations.AddConstraint(model_name='message', constraint=models.UniqueConstraint(fields=('user', 'course', 'client_id'), name='unique_chat_message_request')),
        migrations.AddIndex(model_name='message', index=models.Index(fields=['course', 'id'], name='chat_course_history_idx')),
    ]
