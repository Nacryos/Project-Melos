const fs = require('fs');
const d = require('docx');
const path = require('path');
const SRC = path.join(__dirname, '..', 'data', 'campbell_glp', 'alcaeus_five_corrected.jsonl');
const OUT = process.argv[2] || 'C:/Users/alvin/melos/output/Alcaeus_political_songs_Campbell.docx';
const FONT = 'Times New Roman';
const recs = fs.readFileSync(SRC, 'utf8').split(/\r?\n/).filter(l => l.trim()).map(JSON.parse);
const order = ['34a', '129', '130b', '326', '350'];
const byId = Object.fromEntries(recs.map(r => [r.id.split(':').pop(), r]));
const editions = [...new Set(recs.map(r => r.edition))];
const el = { value: 'el-GR' };

function pageRef(r) {
  const ch = (r.metadata && r.metadata.source_excerpt_chunks) || [];
  const pp = [...new Set(ch.map(c => c.printed_page).filter(p => p != null))].sort((a, b) => a - b);
  if (!pp.length) return '';
  const s = pp.length === 1 ? `p. ${pp[0]}` : `pp. ${pp[0]}\u2013${pp[pp.length - 1]}`;
  const ef = r.metadata.edition_fragment, af = r.metadata.assignment_fragment;
  return `Campbell ${s}` + (ef && af && ef !== af ? `; printed as fr. ${ef}` : '');
}

const children = [
  new d.Paragraph({ heading: d.HeadingLevel.TITLE, children: [new d.TextRun({ text: 'Alcaeus, political songs \u2014 Campbell, Greek Lyric Poetry' })] }),
  new d.Paragraph({ style: 'Subtitle', children: [new d.TextRun('Wednesday 10/7 \u00b7 Fragments 34a, 129, 130b, 326, 350')] }),
];
for (const key of order) {
  const r = byId[key];
  if (!r) throw new Error('missing ' + key);
  const ref = pageRef(r);
  const hRuns = [new d.TextRun(`Fragment ${key}`)];
  if (ref) hRuns.push(new d.TextRun({ text: `  (${ref})`, bold: false, size: 22 }));
  children.push(new d.Paragraph({ heading: d.HeadingLevel.HEADING_1, children: hRuns }));
  for (const line of r.text.split('\n')) {
    children.push(new d.Paragraph({ style: 'GreekVerse', children: line ? [new d.TextRun({ text: line, language: el })] : [] }));
  }
}
const note = 'Text reproduced from the edition-page excerpts accepted on 2026-10-07 (machine-corrected OCR checked against the printed pages), with eleven lines corrected to the page images on 2026-10-08 (34a.10; 129.6, 14, 16, 18, 22, 27; 130b.16, 21, 23, 29); square brackets mark letters supplied by the editor, underdots doubtful letters, spaced dots lost letters.';
children.push(new d.Paragraph({ style: 'NoteText', border: { top: { style: d.BorderStyle.SINGLE, size: 4, color: '999999', space: 6 } }, spacing: { before: 480 }, children: [new d.TextRun(note)] }));
children.push(new d.Paragraph({ style: 'NoteText', children: [new d.TextRun('Edition: '), new d.TextRun({ text: editions.join('; '), italics: false })] }));

const doc = new d.Document({
  creator: 'Alvin', title: 'Alcaeus, political songs \u2014 Campbell, Greek Lyric Poetry',
  styles: {
    default: { document: { run: { font: FONT, size: 24 } } },
    paragraphStyles: [
      { id: 'Title', name: 'Title', basedOn: 'Normal', next: 'Normal', run: { font: FONT, size: 36, bold: true }, paragraph: { spacing: { after: 80 } } },
      { id: 'Subtitle', name: 'Subtitle', basedOn: 'Normal', next: 'Normal', run: { font: FONT, size: 24, italics: true, color: '444444' }, paragraph: { spacing: { after: 240 } } },
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 28, bold: true }, paragraph: { spacing: { before: 360, after: 160 }, keepNext: true, outlineLevel: 0 } },
      { id: 'GreekVerse', name: 'Greek Verse', basedOn: 'Normal', run: { font: { ascii: FONT, hAnsi: FONT, cs: FONT, eastAsia: FONT }, size: 24, language: el }, paragraph: { alignment: d.AlignmentType.LEFT, spacing: { line: 360, after: 0 } } },
      { id: 'NoteText', name: 'Note Text', basedOn: 'Normal', run: { font: FONT, size: 20, color: '444444' }, paragraph: { spacing: { after: 120, line: 276 } } },
    ],
  },
  sections: [{ properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } }, children }],
});
d.Packer.toBuffer(doc).then(b => { fs.writeFileSync(OUT, b); console.log('wrote', OUT); });
