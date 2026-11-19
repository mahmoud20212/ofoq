"""Local Lucide asset integrity, independent of user data or services."""
import re
from pathlib import Path
from xml.etree import ElementTree

from django.template.loader import get_template, render_to_string
from django.test import SimpleTestCase


class LucideIconTests(SimpleTestCase):
    root = Path(__file__).resolve().parent.parent

    def setUp(self):
        self.sprite = self.root / 'courses/static/vendor/lucide/masar-icons.svg'
        self.symbols = {node.attrib['id']: node for node in ElementTree.parse(self.sprite).getroot()}

    def test_all_template_icon_references_exist_in_local_sprite(self):
        for folder in ['courses/templates', 'students/templates', 'chat/templates']:
            for path in (self.root / folder).rglob('*.html'):
                for name in re.findall(r"masar-icons\.svg' %}#([a-z-]+)", path.read_text(encoding='utf-8')):
                    with self.subTest(template=str(path.relative_to(self.root)), icon=name):
                        self.assertIn(name, self.symbols)

    def test_semantic_dashboard_names_and_brand_icons_render(self):
        for name in ['cap', 'graduation-cap', 'dashboard', 'home', 'book', 'comments', 'file',
                     'heart', 'play', 'lock', 'theme', 'settings', 'linkedin', 'github', 'globe']:
            with self.subTest(icon=name):
                html = render_to_string('courses/icon.html', {'name': name})
                self.assertIn('lucide-icon', html)
                self.assertIn(f'#{name}', html)
                self.assertIn(name, self.symbols)
                self.assertIn('aria-hidden="true"', html)

    def test_sprite_has_valid_viewboxes_paths_and_attribution(self):
        self.assertIn('Lucide 0.468.0', self.sprite.read_text(encoding='utf-8'))
        for name, node in self.symbols.items():
            with self.subTest(icon=name):
                self.assertGreater(float(node.attrib['viewBox'].split()[2]), 0)
                self.assertTrue(list(node))
        for name in ['circle-check', 'minus']:
            ElementTree.parse(self.sprite.parent / f'{name}.svg')
        self.assertTrue((self.sprite.parent / 'LICENSE.txt').exists())

    def test_base_templates_supply_local_sprite_and_shared_styling(self):
        for template in ['courses/site.html', 'students/dashboard/base.html', 'base.html']:
            source = get_template(template).template.source
            self.assertIn('data-icon-sprite=', source)
            self.assertIn('css/lucide-icons.css', source)

    def test_favorite_icon_preserves_both_visual_states(self):
        source = get_template('students/dashboard/favorite-button.html').template.source
        self.assertIn('#heart-regular', source)
        self.assertIn('#heart"', source)
        self.assertIn('aria-pressed=', source)
