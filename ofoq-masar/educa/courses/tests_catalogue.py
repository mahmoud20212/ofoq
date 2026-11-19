from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from courses.models import Course, Subject, CartItem


@override_settings(ALLOWED_HOSTS=['testserver'], MIDDLEWARE=[
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
])
class CatalogueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = get_user_model().objects.create_user(username='teacher', first_name='سارة', last_name='محمد')
        cls.student = get_user_model().objects.create_user(username='student', password='test-only-password')
        cls.subject = Subject.objects.create(title='البرمجة', slug='programming')
        cls.other = Subject.objects.create(title='التصميم', slug='design')
        cls.course = Course.objects.create(status='published', owner=cls.teacher, subject=cls.subject, title='تعلم بايثون', slug='python', overview='برمجة تطبيقات')
        for i in range(13):
            Course.objects.create(status='published', owner=cls.teacher, subject=cls.other, title=f'Design {i:02}', slug=f'design-{i}', overview='رسم')

    def test_search_filters_and_pagination(self):
        response=self.client.get('/courses/', {'q':'بايثون','subject':'programming','sort':'title'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(list(response.context['courses']),[self.course])
        self.assertContains(response,'تعلم بايثون')
        self.assertEqual(self.client.get('/courses/',{'q':'سارة'}).context['paginator'].count,14)
        self.assertEqual(self.client.get('/courses/',{'q':'سارة محمد'}).context['paginator'].count,14)
        response=self.client.get('/courses/',{'subject':'design','sort':'title'})
        self.assertEqual(len(response.context['courses']),12)
        self.assertContains(response,'subject=design')
        self.assertContains(response,'page=2')
        self.assertEqual(self.client.get('/courses/',{'subject':'design','page':2}).context['courses'][0].subject,self.other)
        self.assertEqual(self.client.get('/courses/',{'q':'not-found'}).context['paginator'].count,0)

    def test_sort_and_subject_redirect(self):
        self.assertEqual(self.client.get('/courses/',{'sort':'oldest'}).context['courses'][0],self.course)
        self.assertEqual(self.client.get('/courses/',{'sort':'invalid'}).context['sort'],'newest')
        self.assertRedirects(self.client.get('/course/subject/programming/'),'/courses/?subject=programming')
        self.assertEqual(self.client.get('/courses/?subject=missing').status_code,404)

    def test_current_courses_cannot_be_added(self):
        self.client.post(f'/cart/add/{self.course.pk}/')
        self.assertEqual(self.client.session.get('masar_cart',[]),[])
        self.assertContains(self.client.get('/cart/'),'سلتك فارغة')
        self.assertNotContains(self.client.get('/courses/'),f'/cart/add/{self.course.pk}/')

    @patch('courses.cart.price_for',return_value=Decimal('19.50'))
    def test_guest_cart_duplicates_totals_remove_and_merge(self,price):
        url=f'/cart/add/{self.course.pk}/'
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(self.client.session['masar_cart'],[self.course.pk])
        response=self.client.get('/cart/')
        self.assertEqual(response.context['cart_total'],Decimal('19.50'))
        self.assertEqual(response.context['cart_count'],1)
        self.client.force_login(self.student)
        self.assertEqual(CartItem.objects.filter(user=self.student).count(),1)
        self.assertNotIn('masar_cart',self.client.session)
        self.client.post(f'/cart/remove/{self.course.pk}/')
        self.assertEqual(CartItem.objects.count(),0)

    @patch('courses.cart.price_for',return_value=Decimal('12.00'))
    def test_owned_courses_removed_and_merge_deduplication(self,price):
        second=Course.objects.exclude(pk=self.course.pk).first()
        self.course.students.add(self.student)
        CartItem.objects.create(user=self.student,course=second)
        session=self.client.session
        session['masar_cart']=[self.course.pk,second.pk,second.pk]
        session.save()
        self.client.force_login(self.student)
        self.assertEqual(list(CartItem.objects.values_list('course_id',flat=True)),[second.pk])
        response=self.client.get('/cart/')
        self.assertEqual(response.context['cart_total'],Decimal('12.00'))
        with patch('courses.cart.price_for',return_value=None):
            self.assertContains(self.client.get('/cart/'),'سلتك فارغة')
        self.assertEqual(CartItem.objects.count(),0)

    def test_cart_mutations_require_post_and_csrf(self):
        self.assertEqual(self.client.get(f'/cart/add/{self.course.pk}/').status_code,405)
        csrf=Client(enforce_csrf_checks=True)
        self.assertEqual(csrf.post(f'/cart/add/{self.course.pk}/').status_code,403)

    def test_price_adapter_rejects_unknown_prices(self):
        from courses.cart import price_for
        from types import SimpleNamespace as S
        self.assertIsNone(price_for(self.course))
        for amount in ['NaN','-2','0','abc']:
            self.assertIsNone(price_for(S(is_paid=True,price=amount)))
        self.assertEqual(price_for(S(is_paid=True,price='9.99')),Decimal('9.99'))
