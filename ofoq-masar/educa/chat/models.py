from django.conf import settings
from django.db import models


class Message(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='chat_messages',
        verbose_name='المرسل',
    )
    course = models.ForeignKey(
        'courses.Course',
        on_delete=models.PROTECT,
        related_name='chat_messages',
        verbose_name='الدورة',
    )
    content = models.TextField('الرسالة')
    sent_on = models.DateTimeField('تاريخ الإرسال', auto_now_add=True)
    client_id = models.UUIDField('معرّف طلب الإرسال', null=True, blank=True)

    class Meta:
        verbose_name = 'رسالة نقاش'
        verbose_name_plural = 'رسائل النقاش'
        constraints = [models.UniqueConstraint(fields=['user', 'course', 'client_id'], name='unique_chat_message_request')]
        indexes = [models.Index(fields=['course', 'id'], name='chat_course_history_idx')]

    def __str__(self):
        return f'{self.user} — {self.course} — {self.sent_on}'
