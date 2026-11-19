from decimal import Decimal

from django.template import Context, Template
from django.test import SimpleTestCase

from courses.templatetags.course import compact_number


class AssessmentNumberDisplayTests(SimpleTestCase):
    def test_trailing_zeros_removed_without_rounding(self):
        for value, expected in [('2.00', '2'), ('100.00', '100'), ('2.50', '2.5'),
                                ('0.00', '0'), ('0.05', '0.05'), ('12.1250', '12.125'),
                                (10, '10'), (Decimal('50.00'), '50'), ('-0.00', '0')]:
            with self.subTest(value=value):
                self.assertEqual(compact_number(value), expected)

    def test_template_displays_numeric_strings_and_decimals_consistently(self):
        template = Template('{% load course %}{{ score|compact_number }} · {{ percent|compact_number }}%')
        self.assertEqual(template.render(Context({'score': Decimal('2.50'), 'percent': '50.00'})), '2.5 · 50%')

    def test_empty_and_invalid_values_do_not_break_rendering(self):
        self.assertEqual(compact_number(None), '')
        self.assertEqual(compact_number(''), '')
        self.assertEqual(compact_number('not a number'), 'not a number')
