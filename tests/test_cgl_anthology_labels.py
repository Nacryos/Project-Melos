"""Synthetic HTML fixtures for source-label extraction, never corpus entries."""

import unittest

from scripts.ingest_p2_cgl_anthology import (
    cited_edition_label,
    parse_catalog,
    parse_text_page,
)


class CglSourceLabelTests(unittest.TestCase):
    def test_compound_edition_precedes_component(self):
        for printed in ("Lobel-Page", "Lobel–Page", "Lobel — Page"):
            with self.subTest(printed=printed):
                self.assertEqual(cited_edition_label(f"απ. 6 {printed}"), printed)
        self.assertEqual(cited_edition_label("απ. 286 Page"), "Page")
        self.assertEqual(cited_edition_label("απ. S8"), "")
        self.assertEqual(cited_edition_label("απ. 1 NotPage"), "")

    def test_multiple_catalog_header_bands(self):
        # Deliberately fictional groups: the parser must follow DOM scope, not
        # literary knowledge or hardcoded assignments for a fragment number.
        html = b'''<div class="span9">
        <h3 style="background: gray">Section</h3><h3>Author</h3>
        <table><tr><th>First A</th><th>First B</th></tr>
        <tr><td><a href="?text_id=184">178 Page</a></td>
        <td><a href="?text_id=187">S7 (=184 Page)</a></td></tr>
        <tr><th>Later A</th><th>Later B</th></tr>
        <tr><td><a href="?text_id=199">192 Page</a></td>
        <td><a href="?text_id=201">S148</a></td></tr>
        </table></div>'''
        rows = parse_catalog(html)
        self.assertEqual([r["group"] for r in rows],
                         ["First A", "First B", "Later A", "Later B"])
        self.assertEqual(rows[2]["catalog_label"], "192 Page")
        self.assertEqual(rows[2]["text_id"], 199)
        self.assertTrue(all(r["author"] == "Author" for r in rows))

    def test_page_preserves_full_citation(self):
        # Artificial one-word Greek block is only a parser fixture.
        citation = "απ. 34a.1-12 Lobel-Page"
        html = f'''<div class="part-header"><h2>Author</h2>
        <h3>{citation}</h3></div><div class="left-part">
        <div class="anth_text"><p>λόγος</p></div></div>'''.encode()
        page = parse_text_page(html, {"author": "Author", "catalog_label": "fallback"})
        self.assertEqual(page["citation"], citation)
        self.assertEqual(page["edition_token"], "Lobel-Page")

    @staticmethod
    def translation_fixture(tabs, panes):
        return f'''<div class="part-header"><h2>Fixture</h2><h3>1 Page</h3></div>
        <div class="left-part"><div class="anth_text">λόγος</div></div>
        <div class="right-part"><ul class="nav-tabs">{tabs}</ul>
        <div class="tab-content">{panes}</div></div>'''.encode()

    def test_translation_tabs_resolve_by_target_not_position(self):
        html = self.translation_fixture(
            '<a href="#m1" title="Translator A" data-toggle="tab">A</a>'
            '<a href="#m2" title="Translator B" data-toggle="tab">B</a>',
            '<div class="tab-pane" id="m2"><div class="anth_text">Fixture B</div></div>'
            '<div class="tab-pane" id="m1"><div class="anth_text">Fixture A</div></div>',
        )
        page = parse_text_page(html, {})
        self.assertEqual([(t["translator"], t["text"], t["pane_id"]) for t in page["translations"]],
                         [("Translator A", "Fixture A", "m1"), ("Translator B", "Fixture B", "m2")])

    def test_missing_duplicate_or_unlinked_translation_panes_fail(self):
        tab = '<a href="#m1" title="Translator A" data-toggle="tab">A</a>'
        pane = '<div class="tab-pane" id="m1"><div class="anth_text">Fixture</div></div>'
        for tabs, panes in [(tab, ""), (tab, pane + pane), (tab + tab, pane), ("", pane)]:
            with self.subTest(tabs=tabs, panes=panes), self.assertRaises(ValueError):
                parse_text_page(self.translation_fixture(tabs, panes), {})


if __name__ == "__main__":
    unittest.main()
