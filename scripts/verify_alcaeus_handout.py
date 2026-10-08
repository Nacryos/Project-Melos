import json, unicodedata as u, docx, zipfile, re
import sys, pathlib
SRC=str(pathlib.Path(__file__).resolve().parents[1]/'data/campbell_glp/alcaeus_five_corrected.jsonl')
OUT=sys.argv[1] if len(sys.argv)>1 else 'C:/Users/alvin/melos/output/Alcaeus_political_songs_Campbell.docx'
recs={json.loads(l)['id'].split(':')[-1]:json.loads(l) for l in open(SRC,encoding='utf8') if l.strip()}
doc=docx.Document(OUT)
secs={};cur=None
for p in doc.paragraphs:
    s=p.style.name
    if s=='Heading 1':
        cur=p.text.split()[1]; secs[cur]=[]; print('HEADING:',p.text)
    elif s=='Greek Verse': secs[cur].append(p.text)
    elif s not in ('Title','Subtitle'): print(s+':',p.text)
ok=True
for k in ['34a','129','130b','326','350']:
    a=u.normalize('NFC','\n'.join(secs[k])); b=u.normalize('NFC',recs[k]['text'])

    eq=a==b; ok&=eq
    print(recs[k]['id'], 'lines=',len(recs[k]['text'].split('\n')), 'paras=',len(secs[k]), 'NFC-equal=',eq, 'raw-equal=','\n'.join(secs[k])==recs[k]['text'])
    if not eq:
        for i,(x,y) in enumerate(zip(a,b)):
            if x!=y: print(' first diff at',i,repr(x),repr(y)); break
        else: print(' length diff',len(a),len(b))
x=zipfile.ZipFile(OUT).read('word/document.xml').decode()
print('el-GR count:',x.count('el-GR'),'ALL OK' if ok else 'FAIL')
