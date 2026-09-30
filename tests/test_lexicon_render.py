"""Renderer checks against the downloaded, provenance-tracked TEI files."""

from pathlib import Path
import unittest

from backend.lexicon_render import render_entry_text
from backend.morphology import normalize


ROOT = Path(__file__).resolve().parents[1]
LSJ = "data/raw/lexica/lsj/CTS_XML_TEI/perseus/pdllex/grc/lsj/grc.lsj.perseus-eng1.xml"
AUTENRIETH = "data/raw/lexica/autenrieth/autenrieth.xml"


class LexiconRenderTests(unittest.TestCase):
    def test_lsj_greek_tags_only(self):
        if not (ROOT / LSJ).is_file():
            self.skipTest("Downloaded LSJ TEI source is unavailable")
        rendered = render_entry_text(LSJ, "n1")
        self.assertIn("σοφοσ wise", normalize(rendered))
        self.assertIn("weak form of the negative ne", rendered)
        self.assertNotIn("sofo/s", rendered)

    def test_autenrieth_named_punctuation_and_greek(self):
        if not (ROOT / AUTENRIETH).is_file():
            self.skipTest("Downloaded Autenrieth TEI source is unavailable")
        rendered = render_entry_text(AUTENRIETH, "n0")
        self.assertIn("composition—(1) ‘privative,’", rendered)
        self.assertIn("ἀν", rendered)
        self.assertIn("(Eng. ‘star’)", rendered)
        self.assertNotIn("&mdash;", rendered)

    def test_autenrieth_entity_parenthesis_is_not_a_beta_code_breathing(self):
        if not (ROOT / AUTENRIETH).is_file():
            self.skipTest("Downloaded Autenrieth TEI source is unavailable")
        # n2180 contains <orth lang="greek">de/at&lpar;o&rpar;</orth>.
        rendered = render_entry_text(AUTENRIETH, "n2180")
        self.assertIn("(ο): defective ipf.", rendered)
        self.assertNotIn("(ὀ", rendered)

    def test_rejects_source_path_escape(self):
        with self.assertRaises(ValueError):
            render_entry_text("../outside.xml", "n1")


if __name__ == "__main__":
    unittest.main()
