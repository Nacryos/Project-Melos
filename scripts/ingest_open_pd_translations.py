"""Re-download and verify public-domain translations of Campbell GLP (1967) translation gaps.

Rebuilds data/open/pd-translations/{translations.jsonl, manifest.json} from Internet Archive items.

Evidence model
  * IA OCR text layer <ia_id>_djvu.xml (downloaded to a cache outside the repo, sha256 in manifest); the leaves used
    are stored verbatim in raw/<source>/<ia_id>_djvu_leaves.json: this is the text that is verified.
  * raw/<source>/<ia_id>_meta.xml   IA item metadata (title, date, publisher, rights statement).
  * raw/<source>/leaf_NNNN.jpg      page image of each leaf used (what the OCR was checked against by eye).
Every translated string below is stored as OCR spans: each group lists the exact OCR wording (whitespace-normalised)
that must occur, in order, on the named leaf, plus the reviewed reading. A reading that differs from the plain
join of its OCR lines is an OCR correction made against the page image and is recorded in the output with its reason.
Any span not found in the freshly downloaded OCR aborts the build (exit 1).

Usage: python scripts/ingest_open_pd_translations.py [--offline]   (--offline: reuse files already in raw/)
"""
from __future__ import annotations

import hashlib, json, re, sys, time, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/open/pd-translations'
RAW = OUT / 'raw'
CAMPBELL = ROOT / 'data/campbell_glp/campbell_glp.jsonl'
UA = 'Melos/1.0 (+https://greeklyric.com)'
DATE = '2026-10-09'
CACHE = Path(__import__('os').environ.get('MELOS_PD_CACHE', Path(__import__('tempfile').gettempdir()) / 'melos-pd-ocr-cache'))

# ---------------------------------------------------------------- sources (bibliographic facts from IA meta.xml + title pages)
SOURCES = {
 'knox1929': dict(ia='charactersofthe00theouoft', image='iiif', language='eng', year=1929,
     title='The Characters of Theophrastus (ed. J. M. Edmonds) with Herodes, Cercidas and the Greek Choliambic Poets (except Callimachus and Babrius)',
     translator='A. D. Knox', publisher='London: W. Heinemann; Loeb Classical Library 225', place_country='UK',
     pd_basis='Published 1929; US copyright term (95 years) ended 2024-12-31, public domain in the US since 2025-01-01. IA possible-copyright-status: "Permission Granted to Digitize Item".'),
 'brooks1896': dict(ia='greeklyricpoets00broo', image='iiif', language='eng', year=1896,
     title='Greek Lyric Poets', translator='Francis Brooks', publisher='London: David Nutt', place_country='UK',
     pd_basis='Published 1896 (before 1931): public domain in the US.'),
 'muller1858': dict(ia='historyofliterat01mluoft', image='iiif', language='eng', year=1858,
     title='A History of the Literature of Ancient Greece, vol. I (K. O. Mueller; English translation by G. C. Lewis, continued by J. W. Donaldson)',
     translator='Sir George Cornewall Lewis (translator of K. O. Mueller)', publisher='London: Longmans [preface 1858; first English ed. 1840]',
     place_country='UK', pd_basis='Published 1858 (before 1931): public domain in the US. IA possible-copyright-status: NOT_IN_COPYRIGHT.'),
 'columbia1912': dict(ia='cu31924022691251', image='iiif', language='eng', year=1912,
     title='Greek Literature: A Series of Lectures Delivered at Columbia University (lecture "Lyric Poetry")',
     translator='Edward Delavan Perry', publisher='New York: The Columbia University Press', place_country='US',
     pd_basis='Published 1912 (before 1931): public domain in the US. Cornell scan note: "There are no known copyright restrictions in the United States on the use of the text."'),
 'marchant1905': dict(ia='cu31924021601640', image='iiif', language='eng', year=1905,
     title="Greek Reader, selected and adapted with English notes from Prof. von Wilamowitz-Moellendorff's Griechisches Lesebuch, vol. I",
     translator='E. C. Marchant (adapting U. von Wilamowitz-Moellendorff)', publisher='Oxford: Clarendon Press', place_country='UK',
     pd_basis='Published 1905 (before 1931): public domain in the US.'),
 'jevons1886': dict(ia='historyofgreekli00jevouoft', image='iiif', language='eng', year=1886,
     title='A History of Greek Literature from the Earliest Period to the Death of Demosthenes', translator='F. B. Jevons',
     publisher='New York: Scribner [London: Griffin]', place_country='US/UK',
     pd_basis='Published 1886 (before 1931): public domain in the US. IA possible-copyright-status: NOT_IN_COPYRIGHT.'),
 'thudichum1859': dict(ia='diegriechischenl00thuduoft', image='iiif', language='deu', year=1859,
     title='Die griechischen Lyriker oder Elegiker, Iambographen und Meliker: ausgewaehlte Proben im Versmass der Urschrift uebersetzt',
     translator='G. Thudichum', publisher='Stuttgart: Metzler', place_country='DE',
     pd_basis='Published 1859 (before 1931): public domain in the US. IA possible-copyright-status: NOT_IN_COPYRIGHT.'),
 'hartung1859': dict(ia='diegriechischen02hartgoog', image='bookreader', language='deu', year=1859,
     title='Die griechischen Elegiker. Griechisch mit metrischer Uebersetzung und pruefenden und erklaerenden Anmerkungen',
     translator='J. A. Hartung', publisher='Leipzig: W. Engelmann', place_country='DE',
     pd_basis='Published 1859 (before 1931): public domain in the US. IA possible-copyright-status: NOT_IN_COPYRIGHT.'),
}
PAGES = {  # leaf -> printed page, for every leaf image kept as evidence
 'knox1929': {177: '5', 178: '6', 212: '40', 213: '41', 214: '42', 215: '43', 226: '54', 227: '55'},
 'brooks1896': {23: '9', 25: '11', 26: '12', 27: '13', 28: '14'}, 'muller1858': {242: '186'}, 'columbia1912': {81: '70'},
 'marchant1905': {12: '3'}, 'jevons1886': {175: '153'}, 'thudichum1859': {116: '110'}, 'hartung1859': {82: '68', 83: '69'},
}

def G(ocr, fixed=None, why=None):
    """One reviewed unit: OCR wording (list of OCR lines/parts, in order) -> reviewed reading (None = plain join)."""
    return {'ocr': ocr, 'fixed': fixed, 'why': why}

FN = 'footnote reference numeral printed after the word (not part of the translation) misread by OCR; removed'
LONG_S = 'Fraktur OCR error corrected from the page image (long s and Fraktur letter forms); spelling as printed, long s written as s'

# ---------------------------------------------------------------- reviewed spans (checked by eye against raw/<source>/leaf_NNNN.jpg)
KNOX_56_57 = dict(source='knox1929', leaf=213, join='\n', groups=[
    G(['56 [Τ] say dear son of Maia, Cyllene’s'], 'I’ll say dear son of Maia, Cyllene’s', 'page reads "56  I’ll say"; Knox fragment number dropped, "[Τ]" is OCR for "I’ll"'),
    G(['and Lord, give Hipponax a great coat: chilly'], 'Lord, give Hipponax a great coat: chilly', 'marginal "and" belongs to the fragment label "56 and 57", not the verse'),
    G(['57 I am—lI beg you I am right chilly'], 'I am—I beg you I am right chilly', 'fragment label "57" dropped; OCR "lI" for "I"'),
    G(['And my teeth chatter.'])])
KNOX_59 = dict(source='knox1929', leaf=215, join='\n', groups=[
    G(['59 Give to Hipponax a great-coat, shirtlet,'], 'Give to Hipponax a great-coat, shirtlet,', 'fragment label "59" dropped'),
    G(['Sandals and carpet-slippers ; and sixty']),
    G(['Staters of gold by th’ inner wall hidden.'])])

RECORDS = [
 # ------------------------------------------------------------------ Hipponax (Knox 1929)
 dict(campbell_id='campbell-glp:hipponax:24a', role='primary', rendering='partial',
      rendering_note='Campbell 24a joins the Hermes invocation (Knox fr. 57) to the request for clothes and gold (Knox fr. 59). Knox prints no separate English for fr. 57: his single rendering "56 and 57" conflates it with fr. 56 (= Campbell 24b). Both Knox renderings are given, separated by a blank line.',
      translator_ref='Knox frs. 56-57 (joint rendering) + 59', ancient_source_on_page='Tzetzes on Lycophron 855; Priscian/Heliodorus; Plutarch (Knox p. 40-43 notes)',
      identification='Knox Greek fr. 57 (p. 40, leaf 212) "…φίλ᾽ Ἑρμῆ, Μαιαδεῦ Κυλλήν<ι>ε … κάρτα γὰρ κακῶς ῥιγῶ" and fr. 59 (p. 42, leaf 214) "δὸς χλαῖναν Ἱππώνακτι καὶ κυπασσίσκον / καὶ σαμβαλίσκα κἀσκερίσκα καὶ χρυσοῦ / στατῆρας ἑξήκοντα τοὐτέρου τοίχου" = Campbell 24a lines 1-2 and 4-6.',
      greek_leaves=[212, 214], segments=[KNOX_56_57, KNOX_59], segment_join='\n\n'),
 dict(campbell_id='campbell-glp:hipponax:24b', role='primary', rendering='full_with_extra',
      rendering_note='Knox renders fr. 56 (= Campbell 24b) jointly with fr. 57 (the Hermes invocation, part of Campbell 24a) in one four-line version headed "56 and 57".',
      translator_ref='Knox frs. 56-57 (joint rendering)', ancient_source_on_page='Plutarch, Mor. 1058 D (Knox p. 40 note)',
      identification='Knox Greek fr. 56 (p. 40, leaf 212) "δὸς χλαῖναν Ἱππώνακτι· κάρτα γὰρ ῥιγῶ / καὶ βαμβαλύζω" = Campbell 24b.',
      greek_leaves=[212], segments=[KNOX_56_57]),
 dict(campbell_id='campbell-glp:hipponax:25', role='primary', rendering='full',
      rendering_note='Knox fr. 60.', translator_ref='Knox fr. 60', ancient_source_on_page='Tzetzes on Lycophron 855 (Knox p. 42)',
      identification='Knox Greek fr. 60 (p. 42, leaf 214) "ἐμοὶ γὰρ οὐκ ἔδωκας οὔτε χλαῖναν / δασεῖαν … χίμετλα …" = Campbell 25.',
      greek_leaves=[214], segments=[dict(source='knox1929', leaf=215, join='\n', groups=[
          G(['60 To me thou gavest never (yet) great-coat'], 'To me thou gavest never (yet) great-coat', 'fragment label "60" dropped'),
          G(['Shaggy, a cure for ague in winter,']), G(['Nor hid’st in carpet-slippers right shaggy']),
          G(['My feet, to hinder my chillblains growing.'])])]),
 dict(campbell_id='campbell-glp:hipponax:29', role='primary', rendering='full',
      rendering_note='Knox fr. 61; Knox brackets the last line as Tzetzes’ (or a grammarian’s) words.', translator_ref='Knox fr. 61',
      ancient_source_on_page='Tzetzes on Aristophanes, Plutus 90 (Knox p. 42)',
      identification='Knox Greek fr. 61 (p. 42, leaf 214) "ἐμοὶ δὲ Πλοῦτος, ἔστι γὰρ λίην τυφλός, / ἐς τὠκί᾽ ἐλθὼν οὐδάμ᾽ εἶπεν· Ἱππῶναξ, / δίδωμί σοι μνέας ἀργυρίου τριήκοντα" + "καὶ πόλλ᾽ ἔτ᾽ ἄλλα· δείλαιος γὰρ τὰς φρένας" = Campbell 29.',
      greek_leaves=[214], segments=[dict(source='knox1929', leaf=215, join='\n', groups=[
          G(['61 But never came there Plutus, the blind one,'], 'But never came there Plutus, the blind one,', 'fragment label "61" dropped'),
          G(['Unto my house, nor spake thus: ‘ Hipponax']), G(['Minas of silver give I thee thirty.’']),
          G(['[Etcetera : for his intelligence is paltry ].?'], '[Etcetera : for his intelligence is paltry].', FN + '; OCR space before "]" removed')])]),
 dict(campbell_id='campbell-glp:hipponax:70', role='primary', rendering='full',
      rendering_note='Knox fr. 78 (tetrameters).', translator_ref='Knox fr. 78',
      ancient_source_on_page='Suidas s.v. Βούπαλος; Erotian; Galen (Knox p. 54-55)',
      identification='Knox Greek fr. 78 (p. 54, leaf 226) "λάβετέ μευ ταἰμάτια, κόψω Βουπάλου τὸν ὀφθαλμόν· / ἀμφιδέξιος γάρ εἰμι, κοὐχ ἁμαρτάνω κόπτων" = Campbell 70.',
      greek_leaves=[226], segments=[dict(source='knox1929', leaf=227, join='\n', groups=[
          G(['78 Here take my clothes, so in the eye I 11] Bupalus', 'pummel ;'], 'Here take my clothes, so in the eye I ’ll Bupalus pummel ;', 'fragment label "78" dropped; OCR "11]" for "’ll"; turn-over "pummel ;" joined to its verse'),
          G(['For I am ambidexterous and pummelling miss', 'not.?'], 'For I am ambidexterous and pummelling miss not.', FN + '; turn-over joined')])]),
 dict(campbell_id='campbell-glp:hipponax:81', role='primary', rendering='full',
      rendering_note='Knox treats these Stobaeus verses as falsely ascribed to Hipponax (Campbell also brackets the number) and gives "the sense" in English verse in his Introduction; he prints two rows of dots between the 4th and 5th verse.',
      translator_ref='Knox, Introduction p. 5-6 (Stobaeus lxxii. 5; Bergk 72)', ancient_source_on_page='Stobaeus lxxii. 5 (Knox p. 5)',
      identification='Knox quotes the Greek on p. 5 (leaf 177): "Γάμος κράτιστός ἐστιν ἀνδρὶ σώφρονι / τρόπον γυναικὸς χρηστὸν ἔνδον λαμβάνειν· / αὕτη γὰρ ἡ προὶξ οἰκίαν σώζει μόνη. / ὅστις δὲ †τρυφῶς† … / συνεργὸν οὗτος ἀντὶ δεσποίνης ἔχει, / εὔνουν, βεβαίαν εἰς ἅπαντα τὸν βίον" = Campbell [81].',
      greek_leaves=[177], segments=[dict(source='knox1929', leaf=178, join='\n', groups=[
          G(['Best marriage is it for a prudent man']), G(['To take as dower a noble character :']),
          G(['This bridal gift alone can save the house.']), G(['But whoso takes to wife a spendthrift girl']),
          G([], '. . . . . . .', 'row of dots printed on the page (lacuna mark) not captured by OCR'),
          G([], '. . . . . . .', 'second row of dots printed on the page not captured by OCR'),
          G(['He finds a helpmeet, not a mistress stern:']), G(['A kind and true companion to the end.”'])])]),
 # ------------------------------------------------------------------ Archilochus
 dict(campbell_id='campbell-glp:archilochus:71', role='primary', rendering='full', translator_ref='Brooks XIII (Bergk 71)',
      rendering_note='Prose.', ancient_source_on_page=None,
      identification='Greek printed above the English on the same page: "Εἰ γὰρ ὡς ἐμοὶ γένοιτο χεῖρα Νεοβούλης θιγεῖν" = Campbell 71 (εἰ γὰρ ὣς ἐμοὶ γένοιτο χεῖρα Νευβούλης θιγεῖν).',
      segments=[dict(source='brooks1896', leaf=23, join=' ', groups=[G(['O that it might be mine to touch the hand', 'of Neobule.'])])]),
 dict(campbell_id='campbell-glp:archilochus:104', role='primary', rendering='full', translator_ref='Brooks XX (Bergk 84)',
      rendering_note='Prose.', ancient_source_on_page=None,
      identification='Greek on the same page: "Δύστηνος ἔγκειμαι πόθῳ / ἄψυχος, χαλεπῇσι θεῶν ὀδύνῃσιν ἕκητι / πεπαρμένος δι᾽ ὀστέων" = Campbell 104.',
      segments=[dict(source='brooks1896', leaf=25, join=' ', groups=[G(['Hapless I am wrapped in desire, life-bereft,', 'pierced through the marrow with cruel pangs by', 'the will of the gods.'])])]),
 dict(campbell_id='campbell-glp:archilochus:118', role='primary', rendering='full', translator_ref='Brooks XXI (Bergk 85)',
      rendering_note='Prose.', ancient_source_on_page=None,
      identification='Greek on the same page: "Ἀλλά μ᾽ ὁ λυσιμελής, ὦ ᾽ταῖρε, δάμναται πόθος" = Campbell 118.',
      segments=[dict(source='brooks1896', leaf=26, join=' ', groups=[G(['But desire, that makes loose the limbs, over-_', 'comes me, O friend.'], 'But desire, that makes loose the limbs, overcomes me, O friend.', 'line-end hyphen of "over-comes" read as "over-_" by OCR; word rejoined')])]),
 dict(campbell_id='campbell-glp:archilochus:89', role='primary', rendering='full', translator_ref='Brooks XXII (Bergk 86)',
      rendering_note='Prose; Brooks’ headnote ties this and the next two fragments to the fable of the eagle and the fox.', ancient_source_on_page=None,
      identification='Greek on the same page: "Αἶνός τις ἀνθρώπων ὅδε, / ὡς ἆρ᾽ ἀλώπηξ καἰετὸς ξυνωνίην / ἔμιξαν" = Campbell 89.',
      segments=[dict(source='brooks1896', leaf=26, join=' ', groups=[G(['This tale there is among men, that a fox and', 'eagle made once upon a time a league together.'])])]),
 dict(campbell_id='campbell-glp:archilochus:92a', role='primary', rendering='full', translator_ref='Brooks XXIII (Bergk 87)',
      rendering_note='Prose. Brooks prints κάθημαι ("I sit") where Campbell has κάθηται.', ancient_source_on_page=None,
      identification='Greek on the same page: "Ὁρᾷς ἵν᾽ ἔστ᾽ ἐκεῖνος ὑψηλὸς πάγος, / τρηχύς τε καὶ παλίγκοτος, / ἐν τῷ κάθημαι σὴν ἐλαφρίζων μάχην" = Campbell 92a.',
      segments=[dict(source='brooks1896', leaf=26, join=' ', groups=[G(['Thou seest where is yonder lofty crag, rough', 'and frowning, on which 1 sit making light of thy', 'warfare.'], 'Thou seest where is yonder lofty crag, rough and frowning, on which I sit making light of thy warfare.', 'OCR "1" for "I"')])]),
 dict(campbell_id='campbell-glp:archilochus:88', role='primary', rendering='full', translator_ref='Brooks XXVI (Bergk 94)',
      rendering_note='Prose; runs over from p. 13 to p. 14.', ancient_source_on_page=None,
      identification='Greek on p. 13: "Πάτερ Λυκάμβα, ποῖον ἐφράσω τόδε; / τίς σὰς παρήειρε φρένας; / ἧς τὸ πρὶν ἠρήρησθα· νῦν δὲ δὴ πολύς / ἀστοῖσι φαίνεαι γέλως" = Campbell 88.',
      segments=[dict(source='brooks1896', leaf=27, join=' ', groups=[G(['Father Lycambes, what thing is this thou hast', 'devised? Who has made thy mind distraught ?', 'Once thou wast steadfast therein, but now thou'])]),
                dict(source='brooks1896', leaf=28, join=' ', groups=[G(['art a great laughing-stock in the eyes of the', 'people.'])])], segment_join=' '),
 dict(campbell_id='campbell-glp:archilochus:112', role='primary', rendering='full', translator_ref='Brooks XXIX (Bergk 103)',
      rendering_note='Prose. Brooks prints ἀταλὰς where Campbell has ἁπαλὰς.', ancient_source_on_page=None,
      identification='Greek on the same page: "Τοῖος γὰρ φιλότητος ἔρως ὑπὸ καρδίην ἐλυσθείς / πολλὴν κατ᾽ ἀχλὺν ὀμμάτων ἔχευεν, / κλέψας ἐκ στηθέων ἀταλὰς φρένας" = Campbell 112.',
      segments=[dict(source='brooks1896', leaf=28, join=' ', groups=[G(['Such passion of love, winding beneath my', 'heart, shed thick mist over my eyes, stealing', 'the tender soul from my breast.'])])]),
 dict(campbell_id='campbell-glp:archilochus:103', role='primary', rendering='full', translator_ref='Mueller, footnote 3 to p. 186 ("fragment 122", Bergk)',
      rendering_note='Prose rendering quoted inside a footnote.', ancient_source_on_page=None,
      identification='The footnote quotes the Greek before the English: "πόλλ᾽ οἶδ᾽ ἀλώπηξ, ἀλλ᾽ ἐχῖνος ἓν μέγα" = Campbell 103.',
      segments=[dict(source='muller1858', leaf=242, join=' ', groups=[G(["'the", "fox uses many arts, but the hedgehog has one great one,'"])])]),
 dict(campbell_id='campbell-glp:archilochus:79a', role='primary', rendering='partial',
      rendering_note='Prose. Perry omits the opening words ("omitting the first few words of the fragment") and renders from "At Salmydessus" to "he that aforetime was my friend", i.e. Campbell lines 3-16. No Greek is printed.',
      translator_ref='E. D. Perry, lecture "Lyric Poetry", p. 70', ancient_source_on_page='Strassburg papyrus found 1898 (stated on the page)',
      identification='Content match with Campbell 79a: Σαλμυδησσῷ (Salmydessus), Θρήικες ἀκρόκομοι (wild-haired Thracians), δούλιον ἄρτον ἔδων (bread of slavery), γυμνόν / ῥίγει πεπηγότ᾽ (naked and stiff with the cold), φυκία (seaweed), κροτέοι ὀδόντας ὡς κύων (teeth chatter … dog-like), λὰξ δ᾽ ἐπ᾽ ὁρκίοις ἔβη (trampled under foot his oaths), ἑταῖρος ἐὼν τὸ πρίν (aforetime was my friend); the page names the 1898 Strassburg papyrus.',
      segments=[dict(source='columbia1912', leaf=81, join=' ', groups=[G([
          'At Salmydessus may the wild-haired Thracians give to him a', 'joyous welcome — how his cup of woe shall be full as he eats the',
          'bread of slavery ! — to him naked and stiff with the cold ; and may', 'abundant seaweed, cast out of the surge, hold him fast ; may his',
          'teeth chatter as he lies dog-like on his face in helplessness, on the', "shore's edge, close to the waves. Such a sight may I see, for that",
          'he has wronged me and trampled under foot his oaths — he that', 'aforetime was my friend !'])])]),
 # ------------------------------------------------------------------ Phocylides
 dict(campbell_id='campbell-glp:phocylides:4', role='primary', rendering='full', translator_ref='Marchant, Greek Reader I p. 3 (introduction "Maxims and Anecdotes")',
      rendering_note='Prose, in parentheses after the Greek.', ancient_source_on_page=None,
      identification='Greek printed immediately above: "Καὶ τόδε Φωκυλίδεω· πόλις ἐν σκοπέλῳ κατὰ κόσμον / οἰκεῦσα σμικρὴ κρέσσων Νίνου ἀφραινούσης" = Campbell 4.',
      segments=[dict(source='marchant1905', leaf=12, join=' ', groups=[G(['Thus too spake Phocylides: ‘A small city upon a rock', 'wherein discretion abideth is greater than Nineveh in her', 'folly’'])])]),
 dict(campbell_id='campbell-glp:phocylides:3', role='primary', rendering='paraphrase',
      rendering_note='Indirect-speech paraphrase in a literary history, not a line-by-line translation; Jevons cites it as "(4)" (Bergk). See the German verse translation (Thudichum) for a full rendering.',
      translator_ref='Jevons p. 153, "(4)"', ancient_source_on_page=None,
      identification='No Greek printed; Jevons cites Bergk fr. 4, which is Campbell 3 (τί πλέον, γένος εὐγενὲς εἶναι, οἷς οὔτ᾽ ἐν μύθοις ἕπεται χάρις οὔτ᾽ ἐνὶ βουλῇ); content match: birth / speak pleasantly / sensibly.',
      segments=[dict(source='jevons1886', leaf=175, join=' ', groups=[G(['Birth is no good if a man can speak neither', 'pleasantly nor sensibly'])])]),
 dict(campbell_id='campbell-glp:phocylides:3', role='secondary', rendering='full', translator_ref='Thudichum, Phokylides 4 "Unnützer Adel"',
      rendering_note='German verse (elegiac couplet).', ancient_source_on_page=None,
      identification='No Greek printed; "Dieß von Phokylides auch" renders καὶ τόδε Φωκυλίδου; "edler Geburt … Gefälligkeit … Gespräch und Rathe" = γένος εὐγενὲς … χάρις … μύθοις … βουλῇ (Campbell 3).',
      segments=[dict(source='thudichum1859', leaf=116, join='\n', groups=[
          G(['Dieß von Phokylides auch: Mas fürdert eg edler Geburt fein,'], 'Dieß von Phokylides auch: Was fördert es edler Geburt sein,', LONG_S),
          G(['Men die Gefälligfeit nicht in Gefpräch und Nathe begleitet.'], 'Wen die Gefälligkeit nicht in Gespräch und Rathe begleitet.', LONG_S)])]),
 dict(campbell_id='campbell-glp:phocylides:8', role='primary', rendering='full', translator_ref='Thudichum, Phokylides 8 "Stille Sammlung"',
      rendering_note='German verse (hexameter couplet).', ancient_source_on_page=None,
      identification='No Greek printed; "Gehe bei Nacht zu Rathe; bei Nacht ist schärfer des Menschen Sinn … die Ruh’ ist gut beim Suchen der Tugend" = νυκτὸς βουλεύειν, νυκτὸς δέ τοι ὀξυτέρη φρήν … ἡσυχίη δ᾽ ἀρετὴν διζημένῳ ἐσθλή (Campbell 8).',
      segments=[dict(source='thudichum1859', leaf=116, join='\n', groups=[
          G(['Gehe bei Nacht zu Rathe; bei Nacht ift fchärfer des Menfchen'], 'Gehe bei Nacht zu Rathe; bei Nacht ist schärfer des Menschen', LONG_S),
          G(['Sinn und Geift, und die Ruh’ ift gut beim Suchen der Tugend.'], 'Sinn und Geist, und die Ruh’ ist gut beim Suchen der Tugend.', LONG_S)])]),
 # ------------------------------------------------------------------ Mimnermus (German)
 dict(campbell_id='campbell-glp:mimnermus:13', role='primary', rendering='full',
      rendering_note='German elegiacs (11 lines for Campbell’s 11) translating Hartung’s own Greek text (his fr. 19), not Campbell’s: Hartung emends the opening to καὶ μὲν δή (Campbell οὐ μὲν δή, hence German "Und nun erstlich"), reads ἀν᾽ Ἴωνας in line 9 (German "im Jonervolk"; Campbell κείνου ληῶν ἔτ᾽) and differs in lines 6-8 and 11.',
      translator_ref='Hartung, Mimnermos 19', ancient_source_on_page='Stob. VII, 12 (Hartung p. 68)',
      identification='Hartung’s Greek on the same page: "… μένος καὶ ἀγήνορα θυμὸν / τοῖον ἐμεῦ προτέρων πεύθομαι, οἵ μιν ἴδον / Λυδῶν ἱππομάχων πυκινὰς κλονέοντα φάλαγγας / Ἕρμιον ἂμ πεδίον …" = Campbell 13.',
      segments=[dict(source='hartung1859', leaf=82, join='\n', groups=[
          G(['Und nun erftli von befien Gewalt und Heldengemüthe'], 'Und nun erstlich von dessen Gewalt und Heldengemüthe', LONG_S),
          G(['Haben die Früheren mir, welche ihn fannten, erzählt,'], 'Haben die Früheren mir, welche ihn kannten, erzählt,', LONG_S),
          G(['Welche ihn dichte Geſchwader berittener Lyder zerfprengen,'], 'Welche ihn dichte Geschwader berittener Lyder zersprengen,', LONG_S),
          G(['Als ſpeerſchwingenden Mann, fahen im Herwosgefild.'], 'Als speerschwingenden Mann, sahen im Hermosgefild.', LONG_S),
          G(['5 Da fand Pallad Athene auch nie das Geringfte zu tadeln,'], 'Da fand Pallas Athene auch nie das Geringste zu tadeln,', LONG_S + '; line number "5" dropped'),
          G(['Wenn er mit grimmiges Muth Schärfe im vorbe-', 'ren Glied'], 'Wenn er mit grimmiges Muths Schärfe im vorderen Glied', LONG_S + '; turn-over joined'),
          G(['Stärmte, im dauernden Hader des blutigen Schlachten-', '- getümmelß,'], 'Stürmte, im dauernden Hader des blutigen Schlachtengetümmels,', LONG_S + '; turn-over joined'),
          G(['Hart von den Pfeilen und. Speesfchüffen ver Feinde', 'beprängt.'], 'Hart von den Pfeilen und Speerschüssen der Feinde bedrängt.', LONG_S + '; turn-over joined'),
          G(["Dean im Jonervolk gab's keinen jo tapferen Helden"], "Denn im Jonervolk gab's keinen so tapferen Helden", LONG_S)]),
       dict(source='hartung1859', leaf=83, join='\n', groups=[
          G(['10 Mehr in ver Blutarbeit muthigen Schlachtengewühls,'], 'Mehr in der Blutarbeit muthigen Schlachtengewühls,', LONG_S + '; line number "10" dropped'),
          G(['Als er wandelte εἰπε in dem Olanze ver eilenden Sonne —'], 'Als er wandelte einst in dem Glanze der eilenden Sonne —', LONG_S + ' ("εἰπε" is OCR for "einst")')])],
      segment_join='\n'),
]

# ---------------------------------------------------------------- helpers
def ws(s): return re.sub(r'\s+', ' ', s).strip()

def fetch(url, dest: Path, offline: bool):
    if offline and dest.exists():
        return dest.read_bytes()
    for attempt in range(4):
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=180).read()
            if data[:200].lstrip().lower().startswith((b'<html', b'<!doctype html')):
                raise IOError('HTML error page returned')
            dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(data); return data
        except Exception as e:  # loud retry, then fail
            print(f'download failed ({attempt + 1}/4) {url}: {e}', file=sys.stderr); time.sleep(3 * (attempt + 1))
    raise SystemExit(f'FATAL: could not download {url}')

def image_url(src, leaf):
    ia = SOURCES[src]['ia']
    if SOURCES[src]['image'] == 'iiif':
        return (f'https://iiif.archive.org/image/iiif/3/{ia}%2F{ia}_jp2.zip%2F{ia}_jp2%2F{ia}_{leaf:04d}.jp2/full/1200,/0/default.jpg')
    return f'https://archive.org/download/{ia}/page/n{leaf - 1}_w1200.jpg'

def leaves(xml_bytes):
    out = {}
    for el in ET.fromstring(xml_bytes).iter('OBJECT'):
        name = [p.get('value') for p in el.iter('PARAM') if p.get('name') == 'PAGE'][0]
        lines = [ws(' '.join((w.text or '') for w in line.iter('WORD'))) for line in el.iter('LINE')]
        out[int(re.search(r'_(\d+)\.djvu', name).group(1))] = ws(' '.join(l for l in lines if l))
    return out

def autojoin(parts):
    s = ''
    for p in map(ws, parts):
        s = (s[:-1] + p) if s.endswith('-') and p[:1].islower() else (s + ' ' + p if s else p)
    return s

def sha(b): return hashlib.sha256(b).hexdigest()

# ---------------------------------------------------------------- build
def build(offline=False):
    old, old_manifest = {}, None
    if (OUT / 'manifest.json').exists():
        old_manifest = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
        old = {f['path']: f['sha256'] for f in old_manifest['raw_files']}
    files, texts, warnings, ocr_full = [], {}, [], []
    used = {s: set(PAGES[s]) for s in SOURCES}
    for s, meta in SOURCES.items():
        ia = meta['ia']
        p = RAW / s / f'{ia}_meta.xml'; url = f'https://archive.org/download/{ia}/{ia}_meta.xml'
        b = fetch(url, p, offline)
        files.append(dict(path=p.relative_to(OUT).as_posix(), sha256=sha(b), bytes=len(b), url=url))
        # Full OCR layer (2-18 MB each) is cached outside the repo; the leaves used are kept verbatim in raw/.
        lp = RAW / s / f'{ia}_djvu_leaves.json'; url = f'https://archive.org/download/{ia}/{ia}_djvu.xml'
        if offline and lp.exists():
            texts[s] = {int(k): v for k, v in json.loads(lp.read_text(encoding='utf-8'))['leaves'].items()}
        else:
            b = fetch(url, CACHE / f'{ia}_djvu.xml', offline)
            allp = leaves(b); texts[s] = {l: allp[l] for l in sorted(used[s])}
            ocr_full.append(dict(source=s, url=url, sha256=sha(b), bytes=len(b)))
            lp.write_text(json.dumps(dict(ia_item=ia, extracted_from=url, djvu_xml_sha256=sha(b),
                note='Per-leaf OCR text: words of each LINE joined by spaces, whitespace collapsed; lines joined by one space.',
                leaves={str(k): v for k, v in texts[s].items()}), ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        lb = lp.read_bytes()
        files.append(dict(path=lp.relative_to(OUT).as_posix(), sha256=sha(lb), bytes=len(lb), url=url))
        for leaf in sorted(used[s]):
            p = RAW / s / f'leaf_{leaf:04d}.jpg'
            b = fetch(image_url(s, leaf), p, offline)
            files.append(dict(path=p.relative_to(OUT).as_posix(), sha256=sha(b), bytes=len(b), url=image_url(s, leaf), leaf=leaf, printed_page=PAGES[s][leaf]))
    for f in files:
        if f['path'] in old and old[f['path']] != f['sha256']:
            warnings.append(f'sha256 changed since last build: {f["path"]}')
    campbell = {r['id']: r for r in map(json.loads, CAMPBELL.read_text(encoding='utf-8').splitlines()) if r}
    rows, errors = [], []
    for rec in RECORDS:
        src = rec['segments'][0]['source']; meta = SOURCES[src]
        seg_texts, corrections, provenance = [], [], []
        for seg in rec['segments']:
            page = texts[seg['source']][seg['leaf']]; pos = 0; out_lines = []
            for g in seg['groups']:
                if g['ocr']:
                    needle = ws(' '.join(g['ocr']))
                    i = page.find(needle, pos)
                    if i < 0:
                        errors.append(f'{rec["campbell_id"]}: OCR span not found on {seg["source"]} leaf {seg["leaf"]}: {needle!r}'); continue
                    pos = i + len(needle)
                plain = autojoin(g['ocr'])
                reading = g['fixed'] if g['fixed'] is not None else plain
                if reading != plain:
                    corrections.append(dict(leaf=seg['leaf'], ocr=g['ocr'], reading=reading, reason=g['why']))
                out_lines.append(reading)
            seg_texts.append(seg['join'].join(out_lines))
            provenance.append(dict(leaf=seg['leaf'], printed_page=PAGES[seg['source']][seg['leaf']],
                                   image=f'raw/{seg["source"]}/leaf_{seg["leaf"]:04d}.jpg', image_url=image_url(seg['source'], seg['leaf'])))
        poem = campbell[rec['campbell_id']]
        rows.append(dict(
            campbell_id=rec['campbell_id'], campbell_greek_first_line=poem['text'].split('\n')[0],
            role=rec['role'], language=meta['language'], translator=meta['translator'], title=meta['title'], year=meta['year'],
            publisher=meta['publisher'], us_pd_basis=meta['pd_basis'], source_id=src, host='Internet Archive',
            ia_item=meta['ia'], ia_url=f'https://archive.org/details/{meta["ia"]}',
            pages=provenance, greek_pages=[dict(leaf=l, printed_page=PAGES[src][l], image=f'raw/{src}/leaf_{l:04d}.jpg') for l in rec.get('greek_leaves', [])],
            translator_reference=rec['translator_ref'], rendering=rec['rendering'], rendering_note=rec['rendering_note'],
            identification=rec['identification'], ancient_source_on_page=rec['ancient_source_on_page'],
            text=rec.get('segment_join', '\n\n').join(seg_texts), ocr_corrections=corrections,
            verified_against_image=True, verified_on=DATE, model_eligible=False))
    if errors:
        print('\n'.join(errors), file=sys.stderr); raise SystemExit(1)
    body = ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in rows)
    (OUT / 'translations.jsonl').write_bytes(body.encode('utf-8'))
    poems = sorted({r['campbell_id'] for r in rows})
    manifest = dict(
        name='Public-domain translations for Campbell GLP translation gaps', date=DATE, user_agent=UA,
        builder='scripts/ingest_open_pd_translations.py',
        sources=[dict(source_id=k, **{x: v[x] for x in ('ia', 'title', 'translator', 'year', 'publisher', 'language', 'pd_basis')},
                      ia_url=f'https://archive.org/details/{v["ia"]}') for k, v in SOURCES.items()],
        counts=dict(records=len(rows), poems_covered=len(poems),
                    poems_with_english=len({r['campbell_id'] for r in rows if r['language'] == 'eng'}),
                    poems_with_non_english_only=len({r['campbell_id'] for r in rows} - {r['campbell_id'] for r in rows if r['language'] == 'eng'}),
                    ocr_corrections=sum(len(r['ocr_corrections']) for r in rows)),
        translations_jsonl=dict(path='translations.jsonl', sha256=sha(body.encode('utf-8')), bytes=len(body.encode('utf-8'))),
        raw_files=files,
        ocr_text_layers_not_stored=ocr_full or (old_manifest.get('ocr_text_layers_not_stored', []) if old_manifest else []),
        ocr_text_layers_note='Full IA djvu.xml OCR layers are not kept in the repo (82 MB); their URL and sha256 at download time are listed; the leaves used are stored verbatim in raw/<source>/*_djvu_leaves.json.',
        warnings=warnings)
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return manifest['counts'], warnings

if __name__ == '__main__':
    counts, warns = build(offline='--offline' in sys.argv)
    print(json.dumps(dict(counts=counts, warnings=warns), indent=1))
