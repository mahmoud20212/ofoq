from django.template import Template, Context
from django.test import SimpleTestCase, RequestFactory


class VideoEmbedTests(SimpleTestCase):
    def test_embed_sends_origin_referrer_even_with_same_origin_page_policy(self):
        request = RequestFactory().get('/students/courses/1/learn/')
        for url in ['https://www.youtube.com/watch?v=mvZHDpCHphk', 'https://youtu.be/mvZHDpCHphk', 'https://vimeo.com/123456789']:
            with self.subTest(url=url):
                html = Template('{% load embed_video_tags %}{% video url "large" is_secure=True %}').render(Context({'request': request, 'url': url}))
                self.assertIn('src="https://', html)
                self.assertIn('referrerpolicy="strict-origin-when-cross-origin"', html)
                self.assertIn('title="مشغّل الفيديو"', html)
                self.assertIn('allowfullscreen', html)
                self.assertNotIn('src="http://', html)
