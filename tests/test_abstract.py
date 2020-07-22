import unittest
from elifecrossref import abstract


class TestConvertSecTags(unittest.TestCase):

    def test_convert_sec_tags(self):
        string = (
            '<sec id="s1"><title content-type="sub">Section title:</title>'
            '<p>Paragraph.</p></sec>')
        expected = '<jats:p content-type="sub">Section title:</jats:p><p>Paragraph.</p>'
        self.assertEqual(abstract.convert_sec_tags(string), expected)


class TestGetJatsAbstract(unittest.TestCase):

    def test_get_jats_abstract(self):
        string = (
            '<abstract>'
            '<sec id="s1"><title content-type="sub">Section title:</title>'
            '<p>Paragraph.</p></sec>'
            '</abstract>')
        expected = (
            '<jats:sec id="s1"><jats:title content-type="sub">Section title:</jats:title>'
            '<jats:p>Paragraph.</jats:p></jats:sec>')
        self.assertEqual(abstract.get_jats_abstract(string), expected)

    def test_get_jats_abstract_namespace(self):
        string = (
            '<abstract>'
            '<p>Paragraph</p>'
            '<p><bold>DOI:</bold>'
            '<ext-link ext-link-type="doi" xlink:href="10.7554/eLife.15272.001">'
            'https://doi.org/10.7554/eLife.15272.001</ext-link></p>'
            '</abstract>')
        expected = (
            '<jats:p>Paragraph</jats:p><jats:p><jats:bold>DOI:</jats:bold>'
            '<jats:ext-link ext-link-type="doi" xlink:href="10.7554/eLife.15272.001">'
            'https://doi.org/10.7554/eLife.15272.001</jats:ext-link></jats:p>')
        self.assertEqual(abstract.get_jats_abstract(string), expected)
 