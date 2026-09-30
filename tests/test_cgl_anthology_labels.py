"""Synthetic HTML fixtures for source-label extraction, never corpus entries."""

import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from bs4 import BeautifulSoup

from scripts import ingest_p2_cgl_anthology as cgl

from scripts.ingest_p2_cgl_anthology import (
    block_lines,
    cited_edition_label,
    parse_catalog,
    parse_text_page,
)


class CglSourceLabelTests(unittest.TestCase):
    def test_numbering_spans_annotate_source_lines_at_start_or_end(self):
        for markup in (
            '<p><span class="numbering">5</span>Fixture fifth<br/>Fixture sixth<br/>'
            '<span class="numbering">35</span>Fixture last</p>',
            '<p>Fixture fifth<span class="numbering">5</span></p><p>Fixture sixth</p>'
            '<p>Fixture last<span class="numbering">35</span></p>',
        ):
            with self.subTest(markup=markup):
                block = BeautifulSoup(f'<div class="anth_text">{markup}</div>', 'html.parser').div
                self.assertEqual(block_lines(block), [
                    {'label': '5', 'text': 'Fixture fifth'},
                    {'label': '', 'text': 'Fixture sixth'},
                    {'label': '35', 'text': 'Fixture last'},
                ])

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

    def test_inline_translations_use_adjacent_credits(self):
        html = self.translation_fixture(
            '<a data-toggle="tab" title="Translations">Translations</a>',
            '<div class="anth_text"><p>Fixture A</p><p>Another line</p></div>'
            '<div class="pull-right"><i>Translator A</i></div><div class="clearfix"></div>'
            '<div class="anth_text">Fixture B</div>'
            '<div class="pull-right"><i>Translator B</i></div>',
        )
        translations = parse_text_page(html, {})["translations"]
        self.assertEqual([(t["translator"], t["text"]) for t in translations],
                         [("Translator A", "Fixture A\nAnother line"), ("Translator B", "Fixture B")])
        self.assertEqual([t["source_translation_locator"]["block_ordinal"] for t in translations], [1, 2])
        self.assertTrue(all(t["pane_id"] == "" for t in translations))

    def test_inline_missing_ambiguous_or_nonadjacent_credits_fail(self):
        block = '<div class="anth_text">Fixture A</div>'
        credit = '<div class="pull-right"><i>Translator A</i></div>'
        cases = [block, block + block + credit, credit + block,
                 block + '<div class="pull-right"><i>A</i><i>B</i></div>',
                 block + '<div class="pull-right"><i></i></div>',
                 block + '<p>Unscoped note</p>' + credit,
                 block + credit + credit]
        for markup in cases:
            with self.subTest(markup=markup), self.assertRaises(ValueError):
                parse_text_page(self.translation_fixture('', markup), {})

    def test_empty_source_gap_markup_retained_without_invented_text(self):
        html = '''<div class="part-header"><h2>Fixture</h2><h3>1 Page</h3></div>
        <div class="left-part"><div class="anth_text"><p>λόγος
        [<span class="gap indent-4"></span>]</p></div></div>'''.encode()
        line = parse_text_page(html, {})["greek_lines"][0]
        self.assertTrue(line["text"].endswith("[]"))
        self.assertEqual(line["source_gap_markup"][0]["classes"], ["gap", "indent-4"])
        self.assertIn("no missing-letter count inferred", line["plain_text_limitation"])

    def test_stage_only_mode_is_offline_and_rejects_changed_raw_bytes(self):
        # A temporary, explicitly synthetic download manifest tests control flow;
        # these invented HTTP receipts are never accepted as corpus evidence.
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                raw = root / "data/staging/synthetic/raw"
                raw.mkdir(parents=True)
                catalog = b'''<div class="span9"><h3>Fixture Author</h3>
                <table><tr><th>Fixture Group</th></tr><tr><td>
                <a href="?text_id=1">1 Page</a></td></tr></table></div>'''
                poem = self.translation_fixture(
                    '<a href="#m1" title="Fixture Translator" data-toggle="tab">A</a>',
                    '<div class="tab-pane" id="m1"><div class="anth_text">Fixture translation</div></div>')
                files = []
                for filename, url, content in [('browse.html', cgl.CATALOG, catalog),
                                              ('contributors.html', cgl.CONTRIBUTORS, b'Synthetic contributors'),
                                              ('text_1.html', cgl.CATALOG + '?text_id=1', poem)]:
                    path = raw / filename
                    path.write_bytes(content)
                    files.append({'raw_path': path.relative_to(root).as_posix(), 'requested_url': url,
                                  'http_status': 200, 'sha256': cgl.sha256(content), 'bytes': len(content)})
                manifest = raw / 'fetch-manifest.json'
                manifest.write_text(json.dumps({'status': 'raw_download_complete_pending_independent_audit',
                                               'files': files, 'failures': [], 'requested_text_ids': [1]}))
                if corrupt:
                    (raw / 'text_1.html').write_bytes(poem + b'changed')
                stage = root / 'data/staging/synthetic/parsed'
                argv = ['collector', '--parse-raw-manifest', str(manifest), '--stage-dir', str(stage)]
                with patch.object(cgl, 'ROOT', root), patch.object(cgl.SESSION, 'get', side_effect=AssertionError('Network forbidden')), patch('sys.argv', argv):
                    if corrupt:
                        with self.assertRaises(ValueError):
                            cgl.main()
                        self.assertFalse(stage.exists())
                    else:
                        cgl.main()
                        rows = [json.loads(line) for line in (stage / 'cgl-pilot.jsonl').read_text(encoding='utf8').splitlines()]
                        self.assertEqual([row['language'] for row in rows], ['grc', 'ell'])
                        self.assertEqual(rows[1]['parent_id'], rows[0]['id'])
                        self.assertEqual(rows[1]['metadata']['source_translation_locator']['pane_id'], 'm1')
                        inspect_stage = root / 'data/staging/synthetic/inspect'
                        with patch('sys.argv', ['collector', '--parse-raw-manifest', str(manifest),
                                                '--stage-dir', str(inspect_stage), '--inspect-only']):
                            cgl.main()
                        self.assertFalse((inspect_stage / 'cgl-pilot.jsonl').exists())
                        diagnostics = json.loads((inspect_stage / 'parser-report.json').read_bytes())
                        self.assertEqual(diagnostics['counts_by_kind'], {'text': 1, 'translation': 1})
                        self.assertTrue(all('text' not in record for record in diagnostics['records']))

    def test_download_resume_reuses_only_verified_receipts_and_logs_failure(self):
        # Synthetic HTTP stand-in exercises resumability without external data.
        catalog = b'''<div class="span9"><h3>Fixture</h3><table><tr><td>
        <a href="?text_id=1">Fixture 1</a></td><td><a href="?text_id=2">Fixture 2</a>
        </td></tr></table></div>'''
        payloads = {cgl.CATALOG: catalog, cgl.CONTRIBUTORS: b'Fixture credits',
                    cgl.CATALOG + '?text_id=1': b'Fixture page one',
                    cgl.CATALOG + '?text_id=2': b'Fixture page two'}
        calls = []
        fail_last = True

        def fake_fetch(url, path, *, refresh, delay, receipt):
            calls.append(url)
            if url.endswith('text_id=2') and fail_last:
                raise RuntimeError('Synthetic interrupted request')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payloads[url])
            receipt.update({'requested_url': url, 'resolved_url': url, 'http_status': 200,
                            'fetched_at_utc': 'synthetic-test-timestamp', 'cached': False})
            return payloads[url]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / 'data/staging/synthetic/raw'
            with patch.object(cgl, 'ROOT', root), patch.object(cgl, 'fetch', side_effect=fake_fetch):
                with self.assertRaises(RuntimeError):
                    cgl.download_raw_selection(raw, [1, 2], delay=0)
                manifest = json.loads((raw / 'fetch-manifest.json').read_bytes())
                self.assertEqual(len(manifest['files']), 3)
                self.assertEqual(len(manifest['failures']), 1)
                fail_last = False
                before = len(calls)
                manifest = cgl.download_raw_selection(raw, [1, 2], delay=0, resume=True)
                self.assertEqual(calls[before:], [cgl.CATALOG + '?text_id=2'])
                self.assertEqual(len(manifest['files']), 4)
                self.assertIn('resolved_at_utc', manifest['failures'][0])
                (raw / 'text_1.html').write_bytes(b'Tampered fixture')
                before = len(calls)
                with self.assertRaises(ValueError):
                    cgl.download_raw_selection(raw, [1, 2], delay=0, resume=True)
                self.assertEqual(len(calls), before)


if __name__ == "__main__":
    unittest.main()
