// Selection is local state. Only an explicit action contacts the analysis API.
(() => {
  'use strict';
  const MAX_CHARACTERS = 2000, MAX_WORDS = 80;
  async function editorialHash(text) {
    if (!globalThis.crypto?.subtle || typeof TextEncoder !== 'function') return null;
    const bytes = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
  }
  async function verifiedEditorialRows(passage, wrapper) {
    if (!passage?.id || typeof passage.text !== 'string' || wrapper?.version !== 1
      || wrapper.passage_id !== passage.id || !Array.isArray(wrapper.rows)) return [];
    const sourceText = passage.text;
    const digest = await editorialHash(sourceText);
    if (!digest || digest !== wrapper.source_text_sha256) return [];
    const chars = [...sourceText], offsets = [0];
    for (const char of chars) offsets.push(offsets[offsets.length - 1] + char.length);
    const notes = passage.metadata?.transcription_uncertainty || [];
    const noteHash = await editorialHash(JSON.stringify(notes));
    const results = [], ids = new Set(), counts = new Map();
    for (const row of wrapper.rows) counts.set(row?.id,(counts.get(row?.id)||0)+1);
    for (const row of wrapper.rows) {
      if (!row || counts.get(row.id) !== 1 || ids.has(row.id) || row.passage_id !== passage.id || row.source_text_sha256 !== digest
        || !Number.isInteger(row.start) || !Number.isInteger(row.end) || row.start < 0 || row.end <= row.start || row.end > chars.length
        || row.id !== `${passage.id}@${row.start}:${row.end}:editorial`
        || row.start_utf16 !== offsets[row.start] || row.end_utf16 !== offsets[row.end]
        || row.original_text !== sourceText.slice(row.start_utf16, row.end_utf16)
        || row.original_text_sha256 !== await editorialHash(row.original_text)
        || row.evidence_type !== 'printed_editorial_projection' || row.analysis_basis !== 'conditional_on_printed_editorial_reading'
        || ['word_attestation','line_attestation','occurrence_verified','raw_surface_match'].some(key => row[key] !== false)
        || row.uncertainty_note_sha256 !== noteHash || JSON.stringify(row.source_uncertainty_notes) !== JSON.stringify(notes)
        || ['source_url','edition'].some(key => passage[key] != null && row[key] !== passage[key])
        || (passage.raw_sha256 && row.source_raw_sha256 !== passage.raw_sha256)
        || (passage.metadata?.source_pdf_sha256 && row.source_pdf_sha256 !== passage.metadata.source_pdf_sha256)) continue;
      ids.add(row.id);
      if (row.projected_text !== null) {
        const projected = [], map = [], pairs = []; let opened = null, invalid = false;
        for (let index = row.start; index < row.end; index++) {
          const char = chars[index];
          if (char === '[') { if (opened !== null) invalid = true; opened = index; }
          else if (char === ']') { if (opened === null || !chars.slice(opened + 1, index).some(c => /\p{L}/u.test(c))) invalid = true;
            pairs.push({open:opened,close:index}); opened = null; }
          else { map.push({projected_start:projected.length,projected_end:projected.length+1,
            source_start:index,source_end:index+1,source_start_utf16:offsets[index],source_end_utf16:offsets[index+1],
            printed_inside_square_brackets:opened !== null}); projected.push(char); }
        }
        if (invalid || opened !== null || !pairs.length || projected.join('') !== row.projected_text
          || !Array.isArray(row.character_source_map) || map.length !== row.character_source_map.length
          || map.some((item,index) => Object.keys(item).some(key => item[key] !== row.character_source_map[index]?.[key]))
          || !Array.isArray(row.square_bracket_pairs) || pairs.length !== row.square_bracket_pairs.length
          || pairs.some((item,index) => item.open !== row.square_bracket_pairs[index]?.open || item.close !== row.square_bracket_pairs[index]?.close)) continue;
      } else if (row.lookup_eligible !== false) continue;
      if (row.lookup_eligible === true && (row.status !== 'conditional_editorial_reading'
        || row.structural_errors?.length || row.uncertainty_reasons?.length
        || !/^[\p{Script=Greek}][\p{Script=Greek}\p{M}'’ʼ᾽]*$/u.test(row.projected_text || '')
        || row.projected_text.normalize('NFD').includes('\u0323'))) continue;
      results.push(row);
    }
    return passage.text === sourceText ? results : [];
  }
  function editorialChoices(row) {
    const safeUrl = value => {try {const url=new URL(value);return ['http:','https:'].includes(url.protocol) && !url.username && !url.password;} catch {return false;} };
    const analysis = row.analysis;
    if (!row.lookup_eligible || row.selection_relation !== 'fully_contained' || row.lookup_status !== 'complete'
      || analysis?.status !== 'available' || analysis.lookup_form !== row.projected_text
      || analysis.lookup_scope !== 'general_form_no_passage' || analysis.analysis_basis !== 'conditional_on_printed_editorial_reading'
      || analysis.syntax_status !== 'not_requested' || analysis.ranking_status !== 'not_requested'
      || ['word_attestation','occurrence_verified','raw_surface_match'].some(key => analysis[key] !== false)
      || analysis.candidate_count !== analysis.candidate_meanings?.length) return [];
    const groups = new Map();
    for (const candidate of analysis.candidate_meanings) {
      if (!candidate.candidate_id || candidate.basis !== 'conditional_editorial_lookup' || candidate.status !== 'conditional_alternative'
        || !['source_alternative','source_linked_dictionary_path'].includes(candidate.source_basis)
        || ['word_attestation','occurrence_verified','raw_surface_match'].some(key => candidate[key] !== false)) continue;
      const path = candidate.linked_path, proof = candidate.source_provenance || {};
      const linkedProof = candidate.source_basis === 'source_linked_dictionary_path' && path?.source_entry_id && path.target_entry_id
        && path.source_headword === candidate.lemma && Array.isArray(path.claim_ids) && path.claim_ids.length
        && (path.match_method === 'exact_source_form_crossreference' ? path.query_anchor?.source_form?.form === row.projected_text
          : path.match_method === 'literal_source_form_link' && path.source_link?.[1] === `${row.projected_text}#Ancient_Greek`
            && path.source_link[0] === path.printed_form && path.query_anchor?.source_form?.form === path.printed_form);
      const recordedProof = candidate.source_basis === 'source_alternative' && proof.source && safeUrl(proof.source_url);
      if (!linkedProof && !recordedProof) continue;
      const entry = candidate.gloss?.entry_id;
      const senses = (candidate.gloss?.alternatives || []).filter(sense => {
        let url; try { url = new URL(sense.source_url); } catch { return false; }
        return sense.id && sense.text?.trim() && sense.evidence_type === 'dictionary_sense'
          && /^(en|eng|english)$/i.test(sense.language || '') && (sense.lexicon_entry_id || sense.entry_id) === entry
          && sense.source && sense.source_locator && /^[a-f0-9]{64}$/i.test(sense.raw_sha256 || '')
          && ['http:','https:'].includes(url.protocol) && !url.username && !url.password
          && (!candidate.linked_path || (sense.linked_path?.source_entry_id === candidate.linked_path.source_entry_id
            && sense.linked_path?.target_entry_id === candidate.linked_path.target_entry_id && entry === candidate.linked_path.target_entry_id));
      });
      const parse = typeof candidate.parse_short === 'string' && candidate.features && Object.keys(candidate.features).length
        && (linkedProof || proof.analysis_text || proof.analysis_format || proof.source_tags?.length) ? candidate.parse_short : '';
      if (!senses.length && !parse) continue;
      const key = JSON.stringify([candidate.lemma, entry, candidate.features]);
      if (!groups.has(key)) groups.set(key, {lemma:candidate.lemma, parse, senses:[], candidates:[]});
      const group = groups.get(key); group.candidates.push(candidate);
      for (const sense of senses) if (!group.senses.some(item => item.id === sense.id)) group.senses.push(sense);
    }
    return [...groups.values()];
  }
  async function renderEditorialAnalysis(host, data, passage, node, safeLink, selectSourceSpan, current = () => true) {
    const wrapper = data?.editorial_analysis, selection = data?.selection;
    if (!passage || typeof passage.text !== 'string' || wrapper?.scope !== 'conditional_editorial_readings' || wrapper.ranking_status !== 'not_requested'
      || wrapper.limits?.machine_fetches !== 0 || data.passage?.id !== passage?.id
      || data.passage?.text_sha256 !== wrapper.source_text_sha256 || !selection
      || !Number.isInteger(selection.start_utf16) || !Number.isInteger(selection.end_utf16)
      || passage.text.slice(selection.start_utf16,selection.end_utf16) !== selection.text) return false;
    const points = [...passage.text], selected = wrapper.selection;
    if (selected?.offset_unit !== 'codepoint' || !Number.isInteger(selected.start) || !Number.isInteger(selected.end)
      || selected.start < 0 || selected.end <= selected.start || selected.end > points.length
      || points.slice(0,selected.start).join('').length !== selection.start_utf16
      || points.slice(0,selected.end).join('').length !== selection.end_utf16
      || selected.text_sha256 !== await editorialHash(selection.text)) return false;
    const rows = await verifiedEditorialRows(passage, {...wrapper, rows:[...(wrapper.rows || []),...(wrapper.selection_expansion_hints || [])]});
    if (!current() || !rows.length) return false;
    const section = node('section','passage-analysis-section');
    section.append(node('h4','','Printed editorial readings'),node('p','candidate-reason','Conditional on the editor’s printed letters; not attested readings or resolved meanings. The original text is unchanged.'));
    const unknown = node('details','entry-details'); unknown.append(node('summary','','Other marked words'));
    let shown = 0, hidden = 0;
    for (const row of rows) {
      const contained = selected.start <= row.start && row.end <= selected.end;
      const overlaps = row.start < selected.end && row.end > selected.start;
      if (!overlaps || (contained ? row.selection_relation !== 'fully_contained' : row.selection_relation !== 'partial_intersection')) continue;
      const choices = contained ? editorialChoices(row) : [];
      const card = node('div','dictionary-glimpse-entry');
      card.append(node('p','candidate-lemma',row.projected_text ? `${row.original_text} → ${row.projected_text}` : row.original_text));
      if (!contained && row.lookup_status === 'not_requested_partial_selection' && row.lookup_eligible && selectSourceSpan) {
        const action = node('button','text-action','Analyze whole printed word'); action.type = 'button';
        action.addEventListener('click',()=> { if (current()) selectSourceSpan({start:row.start_utf16,end:row.end_utf16,selected_text:row.original_text,offset_unit:'utf16'},true); });
        card.append(action); section.append(card); shown++; continue;
      }
      if (!choices.length) {card.append(node('p','candidate-reason',row.lookup_eligible ? 'No sourced conditional parse or meaning yet.' : 'This marked reading is not eligible for automatic lookup.'));unknown.append(card);hidden++;continue;}
      const more = node('details','entry-details');more.append(node('summary','','More alternatives and sources'));
      choices.forEach((choice,index)=>{
        const part = node('div','candidate');
        if (choice.lemma) part.append(node('p','candidate-lemma',choice.lemma));
        if (choice.parse) part.append(node('p','candidate-analysis',choice.parse));
        choice.senses.forEach((sense,senseIndex)=>{const line=node('p','candidate-gloss',sense.text),link=safeLink(sense.source_url,sense.source);
          if(link)line.append(link);(index < 2 && senseIndex < 2 ? part : more).append(line);});
        (index < 2 ? card : more).append(part);
        for(const candidate of choice.candidates){const proof=node('details','entry-details');proof.append(node('summary','','Source proof'),node('pre','passage-analysis-receipt',JSON.stringify(candidate,null,2)));more.append(proof);}
      });
      card.append(more);section.append(card);shown++;
    }
    if (hidden) section.append(unknown);
    if (!shown && !hidden) return false;
    host.append(section); return true;
  }
  async function renderEditorialWordActions(host, passage, start, end, node, selectSourceSpan, current = () => true) {
    if (!Number.isInteger(start) || !Number.isInteger(end) || !selectSourceSpan) return false;
    if (!passage?.editorial_readings?.rows?.some(row => row.start_utf16 < end && row.end_utf16 > start)) return false;
    const rows = await verifiedEditorialRows(passage, passage?.editorial_readings);
    if (!current()) return false;
    const intersecting = rows.filter(row => row.lookup_eligible && row.start_utf16 < end && row.end_utf16 > start);
    for (const row of intersecting) {
      const box=node('div','dictionary-glimpse-entry');box.append(node('p','candidate-reason',`Printed editorial reading: ${row.original_text} → ${row.projected_text}`));
      const action=node('button','text-action','Analyze whole printed word');action.type='button';
      action.addEventListener('click',()=>{if(current())selectSourceSpan({start:row.start_utf16,end:row.end_utf16,selected_text:row.original_text,offset_unit:'utf16'},true);});box.append(action);host.append(box);
    }
    return intersecting.length > 0;
  }
  // Display identities omit source IDs, not linguistic distinctions. Original
  // rows remain attached so collapsing evidence never deletes provenance.
  function dedupeCandidates(candidates) {
    const stable = value => value && typeof value === 'object'
      ? Array.isArray(value) ? value.map(stable) : Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])]))
      : typeof value === 'string' ? value.normalize('NFC').trim().replace(/\s+/g, ' ') : value;
    const groups = new Map();
    for (const candidate of candidates || []) {
      const identity = JSON.stringify(stable({ lemma: candidate.lemma || candidate.equivalent_form || '',
        form: candidate.matched_form || candidate.attested_form || '',
        analysis: candidate.analysis_text || candidate.analysis || '', features: candidate.features || {},
        inflection: candidate.inflection || {}, dictionary: candidate.dictionary_fields || {},
        homograph: [candidate.homograph_id ?? '',candidate.lemma_identity ?? ''], lemma_raw: candidate.lemma_raw || '',
        source_tags: candidate.source_tags || [], source_raw_tags: candidate.source_raw_tags || [],
        scope: [candidate.candidate_kind,candidate.assertion_type,candidate.basis,candidate.status,
          candidate.match_kind,candidate.edit_distance,candidate.exact_match,candidate.quality,candidate.source_quality,candidate.quarantined,
          candidate.source_consistent,candidate.source_inconsistent,candidate.lemma_link_status,
          candidate.dialect,candidate.dialects] }));
      const previous = groups.get(identity);
      if (previous) {
        previous.evidence_rows.push(candidate);
        if (!previous.gloss && candidate.gloss) previous.gloss = candidate.gloss;
        if (candidate.gloss && !previous.glosses.includes(candidate.gloss)) previous.glosses.push(candidate.gloss);
      } else groups.set(identity, { ...candidate, glosses: candidate.gloss ? [candidate.gloss] : [], evidence_rows: [candidate] });
    }
    return [...groups.values()];
  }
  function groupCandidateDisplays(candidates) {
    const nfc = value => typeof value === 'string' ? value.normalize('NFC').trim() : '';
    const sourceIdentity = value => typeof value === 'string' ? nfc(value) : typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
    const stable = value => value && typeof value === 'object' ? Array.isArray(value) ? value.map(stable)
      : Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value;
    const same = (a,b) => JSON.stringify(stable(a)) === JSON.stringify(stable(b));
    const labels = {
      verb:['POS','VERB'],noun:['POS','NOUN'],adjective:['POS','ADJ'],adverb:['POS','ADV'],pronoun:['POS','PRON'],
      'first-person':['Person','1'],'first person':['Person','1'],'second-person':['Person','2'],'second person':['Person','2'],
      'third-person':['Person','3'],'third person':['Person','3'],singular:['Number','Sing'],plural:['Number','Plur'],dual:['Number','Dual'],
      present:['Tense','Pres'],aorist:['Tense','Aor'],imperfect:['Tense','Imp'],perfect:['Tense','Perf'],pluperfect:['Tense','Pqp'],future:['Tense','Fut'],
      indicative:['Mood','Ind'],subjunctive:['Mood','Sub'],optative:['Mood','Opt'],imperative:['Mood','Imp'],
      infinitive:['VerbForm','Inf'],participle:['VerbForm','Part'],active:['Voice','Act'],middle:['Voice','Mid'],passive:['Voice','Pass'],
      nominative:['Case','Nom'],genitive:['Case','Gen'],dative:['Case','Dat'],accusative:['Case','Acc'],vocative:['Case','Voc'],
      masculine:['Gender','Masc'],feminine:['Gender','Fem'],neuter:['Gender','Neut']
    };
    const allowed = {POS:['VERB','NOUN','ADJ','ADV','PRON'],Person:['1','2','3'],Number:['Sing','Plur','Dual'],
      Tense:['Pres','Aor','Imp','Perf','Pqp','Fut','FutPerf'],Mood:['Ind','Sub','Opt','Imp'],VerbForm:['Inf','Part','Fin'],
      Voice:['Act','Mid','Pass'],Case:['Nom','Gen','Dat','Acc','Voc'],Gender:['Masc','Fem','Neut']};
    function known(row) {
      if (!nfc(row.lemma) || !nfc(row.matched_form) || row.assertion_type === 'model_inference'
        || row.candidate_kind === 'machine_analysis' || row.basis === 'machine_analysis'
        || row.quarantined || row.source_consistent === false || row.source_inconsistent
        || row.edit_distance != null && row.edit_distance !== 0
        || row.match_kind && !['indexed_form','lexicon_headword'].includes(row.match_kind)
        || row.exact_match === false
        || /propos|reject|uncertain|review/i.test(row.status || '')
        || [row.quality,row.source_quality].some(value=>/quarantin|inconsisten|rejected|needs_review|machine_proposed/i.test(value || ''))
        || row.lemma_link_status === 'ambiguous_source_lemmas') return null;
      const indexed = row.edit_distance === 0 && ['indexed_form','lexicon_headword'].includes(row.match_kind) && row.source_url;
      const claimed = row.status === 'source_claim' && row.assertion_type === 'extracted_annotation'
        && row.claim_ids?.length && row.evidence_refs?.length;
      if (!indexed && !claimed) return null;
      if (row.source_tags != null && !Array.isArray(row.source_tags)) return null;
      const fields = {};
      let invalid = false;
      const add = (key,value) => { if (!allowed[key]?.includes(value) || fields[key] && fields[key] !== value) invalid=true; else fields[key]=value; };
      for (const [key,value] of Object.entries(row.features || {})) add(key,value);
      const tags = [...(row.source_tags || []), ...(Array.isArray(row.analysis) ? row.analysis : []),
        ...(typeof row.analysis_text === 'string' ? row.analysis_text.split(' · ') : [])];
      for (const tag of tags) {
        const label=nfc(tag).toLowerCase();
        if (labels[label]) add(...labels[label]);
        else if (label && !['form-of','alt-of'].includes(label)) invalid=true;
      }
      if (invalid || !Object.keys(fields).length) return null;
      return {fields,identity:JSON.stringify([nfc(row.lemma),nfc(row.matched_form),sourceIdentity(row.homograph_id),
        sourceIdentity(row.lemma_identity),nfc(row.lemma_raw)]),
        other:stable([row.source_raw_tags || [],row.inflection || {},row.dictionary_fields || {},row.dialect || '',row.dialects || []])};
    }
    const rows = candidates.map(row=>({...row})), facts=rows.map(row=>{
      const fact=known(row);
      // Revalidate every retained record after exact deduplication. A model,
      // normalized hit or conflicting qualifier must not inherit source status.
      return fact && (!row.evidence_rows || Array.isArray(row.evidence_rows)
        && row.evidence_rows.length && row.evidence_rows.every(member=>same(known(member),fact))) ? fact:null;
    }), parents=new Map();
    for (let i=0;i<rows.length;i++) {
      const partial=facts[i];if(!partial)continue;
      const fuller=[];
      for(let j=0;j<rows.length;j++) {
        const full=facts[j];
        if(i===j || !full || full.identity!==partial.identity
          || !same(full.other,partial.other) || Object.keys(full.fields).length<=Object.keys(partial.fields).length)continue;
        if(Object.entries(partial.fields).every(([key,value])=>full.fields[key]===value))fuller.push(j);
      }
      if(fuller.length===1)parents.set(i,fuller[0]);
    }
    for(const [index,parent] of parents) {
      let root=parent;while(parents.has(root))root=parents.get(root);
      (rows[root].partial_evidence_rows ||= []).push(...(rows[index].evidence_rows || [candidates[index]]));
    }
    return rows.filter((_,index)=>!parents.has(index));
  }
  function renderPartialCandidateEvidence(host, candidate, node) {
    const rows=candidate.partial_evidence_rows || [];if(!rows.length)return;
    const box=node('details','entry-details partial-source-parses');
    box.append(node('summary','',`Additional source records · ${rows.length} incomplete ${rows.length===1?'parse':'parses'}`),
      node('p','candidate-reason','These records supply fewer grammatical fields. They are compatible source alternatives, not a combined or contextually verified parse.'));
    for(const row of rows) {
      const part=node('div','partial-source-parse');
      part.append(node('p','candidate-analysis',row.analysis_text || (Array.isArray(row.analysis)?row.analysis.join(' · '):row.analysis) || JSON.stringify(row.features || {})),
        node('p','candidate-reason',[row.lemma,row.source,row.id].filter(Boolean).join(' · ')),
        node('pre','passage-analysis-receipt',JSON.stringify(row,null,2)));box.append(part);
    }
    host.append(box);
  }
  async function machineSubentryMeanings(result, token, displayedCandidate) {
    // Display-only dictionary alternatives for a receipt-backed machine lemma.
    // Never add these definitions to ordinary glosses, Jev, or source parses.
    try {
      const catalog=result?.machine_subentry_evidence;
      if(catalog?.version!==1 || catalog.ranking_status!=='unsupported_source_type'
        || token.partial_word || token.editorial_fragment || token.kind!=='word')return [];
      const stable=value=>value && typeof value==='object' ? Array.isArray(value)?value.map(stable)
        :Object.fromEntries(Object.keys(value).sort().map(key=>[key,stable(value[key])])):value;
      const json=value=>JSON.stringify(stable(value)), equal=(a,b)=>json(a)===json(b);
      const hash=value=>editorialHash(json(value)), hex=value=>typeof value==='string' && /^[a-f0-9]{64}$/.test(value);
      const own=(pool,key)=>typeof key==='string' && pool && Object.hasOwn(pool,key)?pool[key]:null;
      const ids=value=>Array.isArray(value) && value.every(id=>typeof id==='string' && id) && new Set(value).size===value.length;
      const url=value=>{try {const parsed=new URL(value);return ['https:','http:'].includes(parsed.protocol) && !parsed.username && !parsed.password;}catch{return false;}};
      const lookup=value=>{if(typeof value!=='string')return null;const word=value.trim().normalize('NFC');
        return /^(?:\p{Script=Greek}\p{M}*)+(?:[-‐](?:\p{Script=Greek}\p{M}*)+)*$/u.test(word)?word.replace(/[-‐]/gu,''):null;};
      const snapshot=json({catalog,token,displayedCandidate,interlinear:result.interlinear});
      const originals=(result.tokens || []).filter(row=>row.id===token.id);
      if(originals.length!==1 || !equal(originals[0],token) || token.machine?.status!=='ok' || token.machine.form!==(token.form||token.text))return [];
      const rows=(token.machine?.machine_candidates || []).filter(row=>row.id===displayedCandidate.id);
      if(rows.length!==1)return [];
      const candidate=rows[0];
      if(candidate.basis!=='machine_analysis' || candidate.candidate_kind!=='machine_analysis'
        || !Object.keys(candidate).every(key=>equal(candidate[key],displayedCandidate[key])))return [];
      const readingRows=(result.interlinear?.readings || []).flatMap(reading=>reading.tokens || []).filter(row=>
        (row.token_id===token.id || row.id===token.id) && row.text===token.text && row.start_utf16===token.start_utf16 && row.end_utf16===token.end_utf16);
      if(readingRows.length!==1)return [];
      const views=(readingRows[0].candidate_meanings || []).filter(row=>row.candidate_id===candidate.id);
      if(views.length!==1 || views[0].basis!=='machine_analysis' || views[0].lemma!==candidate.lemma)return [];
      const reference=token.machine_subentries, refs=views[0].machine_subentry_alternatives;
      if(!Array.isArray(refs) || !refs.length || !reference || reference.ranking_status!=='unsupported_source_type')return [];
      const inventory=own(catalog.inventories,reference.inventory_ref);
      if(!inventory || !hex(reference.inventory_ref) || inventory.version!=='receipt-lemma-explicit-subentry-v1'
        || inventory.form!==(token.form||token.text) || inventory.scope!=='dictionary_definitions_for_parser_lemma_not_occurrence_attestation'
        || inventory.contextually_selected!==false || !['available','partial','source_evidence_only','no_exact_subentry'].includes(inventory.status)
        || !equal(reference.candidate_refs,inventory.candidates))return [];
      const body=Object.fromEntries(Object.entries(inventory).filter(([key])=>!['dependency_ref','candidates','supporting_subentries','supporting_receipts'].includes(key)));
      body.dependencies=own(catalog.dependencies,inventory.dependency_ref);
      if(!body.dependencies || await hash(body.dependencies)!==inventory.dependency_ref)return [];
      for(const [field,pool] of [['candidates','bindings'],['supporting_subentries','subentries'],['supporting_receipts','receipts']]) {
        if(!ids(inventory[field]))return [];
        body[field]=inventory[field].map(id=>own(catalog[pool],id));if(body[field].some(row=>!row))return [];
      }
      if(await hash(body)!==reference.inventory_ref)return [];
      const rawCandidate=Object.fromEntries(Object.entries(candidate).filter(([key])=>!['lexicon_entry_ids','dictionary_join'].includes(key)));
      const candidateHash=await hash(rawCandidate),output=[],seen=new Set();
      for(const ref of refs) {
        if(ref.inventory_ref!==reference.inventory_ref || ref.ranking_status!=='unsupported_source_type'
          || ref.status!=='unresolved_machine_lemma_dictionary_alternative' || !ids(ref.sense_refs))return [];
        const binding=own(catalog.bindings,ref.binding_ref),evidence=own(catalog.subentries,ref.subentry_ref);
        if(!inventory.candidates.includes(ref.binding_ref) || !inventory.supporting_subentries.includes(ref.subentry_ref)
          || !binding || binding.id!==ref.binding_ref || binding.candidate_id!==candidate.id || binding.lemma!==candidate.lemma
          || binding.form!==(token.form||token.text) || binding.machine_candidate_sha256!==candidateHash || binding.receipt_id!==candidate.receipt_id
          || binding.lookup_key!==lookup(candidate.lemma) || binding.match_method!=='exact_parser_lemma_to_explicit_subentry_orthography'
          || ['occurrence_attested','contextually_selected','surface_equivalence_inferred'].some(key=>binding[key]!==false)
          || !binding.subentry_ids?.includes(ref.subentry_ref) || !binding.english_preview_subentry_ids?.includes(ref.subentry_ref))return [];
        if(binding.id!==`machine-subentry:${await hash(Object.fromEntries(Object.entries(binding).filter(([key])=>key!=='id')))}`)return [];
        const receipt=own(catalog.receipts,binding.receipt_id),source=evidence?.source_subentry,preview=evidence?.english_preview;
        if(!receipt || receipt.id!==binding.receipt_id || !inventory.supporting_receipts.includes(receipt.id) || !hex(receipt.raw_sha256)
          || (receipt.source_form || receipt.request_form)!==(token.form||token.text) || !url(receipt.url)
          || evidence.id!==ref.subentry_ref || source?.id!==ref.subentry_ref || source.lookup_key!==binding.lookup_key
          || lookup(source.orthography)!==source.lookup_key
          || source.evidence_type!=='dictionary_explicit_subentry' || source.scope!=='source_dictionary_orthography_not_morphological_analysis'
          || preview?.eligible!==true || preview.reasons?.length!==0
          || preview.scope!=='parser_lemma_matched_literal_subentry_not_independently_validated_lemma'
          || !hex(source.raw_sha256) || !url(source.source_url) || source.source!=='PerseusDL LSJ TEI'
          || !source.source_locator || !Array.isArray(source.dictionary_senses))return [];
        const tokenReceipt=token.machine.receipt;
        if(!tokenReceipt || ['id','raw_sha256','url','parser_version','source_form','request_form','http_status'].some(key=>
          Object.hasOwn(tokenReceipt,key) && Object.hasOwn(receipt,key) && !equal(tokenReceipt[key],receipt[key])))return [];
        // Keep the resolver's conservative English-preview exclusions even if
        // an older extraction mistakenly labelled a Gloss.-only Latin item en.
        if((source.lookup_key.match(/\p{L}/gu)||[]).length<2 || !['full','suff'].includes(source.orth_extent)
          || source.orth_extent==='suff' && !/[-‐]/u.test(source.orthography)
          || source.citations?.length && source.citations.every(c=>c.text?.trim()==='Gloss.'))return [];
        const sourceIds=source.dictionary_senses.map(sense=>sense.id);
        if(!ids(sourceIds) || !equal(ref.sense_refs,sourceIds))return [];
        for(const sense of source.dictionary_senses) {
          if(!englishTranslation(sense) || sense.evidence_type!=='dictionary_sense' || typeof sense.text!=='string' || !sense.text.trim()
            || sense.lexicon_entry_id!==source.parent_lexicon_entry_id || sense.entry_id!==source.parent_entry_id
            || ['source_url','raw_sha256','raw_path','source'].some(key=>sense[key]!==source[key]) || !sense.source_locator
            || sense.form_scope?.relation!=='variant' || sense.form_scope.text!==source.orthography
            || !equal(sense.form_scope.source_locator,source.source_locator))return [];
          if(!seen.has(sense.id)){output.push({sense,source,binding,receipt,inventory_ref:reference.inventory_ref});seen.add(sense.id);}
        }
      }
      return snapshot===json({catalog,token,displayedCandidate,interlinear:result.interlinear})?output:[];
    } catch {return [];}
  }
  async function renderMachineSubentryMeanings(host,result,token,candidate,node,safeLink,current=()=>true) {
    const meanings=await machineSubentryMeanings(result,token,candidate);
    if(!current() || !meanings.length)return false;
    const box=node('div','passage-dictionary-senses');
    box.append(node('p','candidate-meta-label','Dictionary alternative for this machine parse'));
    let rest;
    for(const [index,item] of meanings.entries()) {
      const row=node('div','passage-dictionary-sense');row.append(node('strong','candidate-gloss',item.sense.text));
      const proof=node('details','entry-details');proof.append(node('summary','','Dictionary source'),
        node('p','candidate-reason',`LSJ · ${item.source.orthography} · not a context-selected meaning`));
      const link=safeLink(item.source.entry_url || item.source.source_url,'Open dictionary entry');if(link)proof.append(link);
      for(const citation of item.source.citations || [])if(typeof citation.text==='string')proof.append(node('p','candidate-reason',citation.text));
      proof.append(node('pre','passage-analysis-receipt',JSON.stringify(item,null,2)));row.append(proof);
      if(index<3)box.append(row);else {if(!rest){rest=node('details','entry-details');rest.append(node('summary','','More dictionary alternatives'));box.append(rest);}rest.append(row);}
    }
    host.append(box);return true;
  }
  function englishTranslation(item) {
    return /^(?:en|eng)(?:-[a-z0-9]{2,8})*$/i.test(String(item?.language || item?.target_language || '').trim());
  }
  function renderPublishedCommentary(host, data, node) {
    const source = data?.context && Object.hasOwn(data.context, 'published_commentary')
      ? data.context.published_commentary : data?.published_commentary;
    if (!source || source.status !== 'available' || source.evidence_type !== 'published_commentary'
      || source.scope !== 'whole_poem_commentary' || source.selection_aligned !== false
      || source.word_attestation !== false || source.line_attestation !== false
      || typeof data.passage?.id !== 'string' || source.parent_id !== data.passage.id
      || source.commentary_id !== `${source.parent_id}:commentary`
      || typeof source.source_title !== 'string' || !source.source_title.trim()
      || !/^[a-f0-9]{64}$/i.test(source.source_pdf_sha256 || '')
      || (data.passage?.metadata?.source_pdf_sha256 && data.passage.metadata.source_pdf_sha256 !== source.source_pdf_sha256)
      || !Array.isArray(source.paragraphs) || !source.paragraphs.length
      || source.paragraph_count !== source.paragraphs.length
      || !source.paragraphs.every(paragraph => typeof paragraph?.text === 'string')) return false;
    const panel = node('details', 'passage-analysis-section entry-details published-commentary');
    panel.append(node('summary', '', 'Published commentary on this poem'),
      node('p', 'candidate-meta-label', source.source_title),
      node('p', 'candidate-reason', 'Whole-poem commentary, not a translation, grammatical parse, or annotation specifically matched to the selected words.'));
    for (const paragraph of source.paragraphs) {
      const part = node('div', 'commentary-hit');
      if (typeof paragraph.citation === 'string' && paragraph.citation) part.append(node('p', 'commentary-source', paragraph.citation));
      part.append(node('p', 'commentary-excerpt', paragraph.text));
      if (paragraph.uncertain_ocr === true) part.append(node('p', 'candidate-reason', 'OCR is uncertain in this source paragraph.'));
      panel.append(part);
    }
    const provenance = node('details', 'entry-details');
    provenance.append(node('summary', '', 'Edition and source record'),
      node('p', 'candidate-reason', source.commentary_id), node('code', '', source.source_pdf_sha256));
    if (typeof source.rights_note === 'string') provenance.append(node('p', 'candidate-reason', source.rights_note));
    panel.append(provenance); host.append(panel);
    return true;
  }
  function renderTranslationComparisons(host, data, node, safeLink) {
    const wrapper = data?.context && Object.hasOwn(data.context, 'translation_comparisons')
      ? data.context.translation_comparisons : data?.translation_comparisons;
    const comparisonScope = row => row?.evidence_type === 'different_edition_translation_comparison'
      && row.scope === 'whole_poem_other_edition' && row.selection_aligned === false
      && row.exact_edition_alignment === false && row.word_attestation === false
      && row.line_attestation === false && row.model_eligible === false;
    if (!wrapper || wrapper.status !== 'available' || !comparisonScope(wrapper)
      || typeof data.passage?.id !== 'string' || wrapper.campbell_record_id !== data.passage.id
      || !Array.isArray(wrapper.translation_comparisons) || !wrapper.translation_comparisons.length
      || wrapper.comparison_count !== wrapper.translation_comparisons.length) return false;
    const items = wrapper.translation_comparisons, ids = new Set();
    const validUrl = value => {
      try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password; } catch { return false; }
    };
    for (const item of items) {
      if (!comparisonScope(item) || !englishTranslation(item) || Object.hasOwn(item, 'parent_id') || Object.hasOwn(item, 'translation_of')
        || typeof item.comparison_id !== 'string' || !item.comparison_id || ids.has(item.comparison_id)
        || typeof item.text !== 'string' || !item.text.trim() || !validUrl(item.source_url)
        || !['translator', 'citation', 'edition'].every(key => typeof item[key] === 'string' && item[key].trim())) return false;
      ids.add(item.comparison_id);
    }
    const panel = node('details', 'passage-analysis-section entry-details translation-comparisons');
    panel.append(node('summary', '', items.length === 1 ? 'English translation · another edition' : 'English translations · other editions'),
      node('p', 'translation-scope', 'Whole-poem comparisons from other editions, not translations aligned to Campbell’s text or to the selected words.'));
    for (const item of items) {
      const card = node('article', 'published-translation');
      card.append(node('p', 'translation-credit', `English · Translator: ${item.translator}`),
        node('p', 'translation-edition', `${item.edition} · ${item.citation}`),
        node('p', 'translation-text', item.text));
      const link = safeLink(item.source_url, 'Published translation source'); if (link) card.append(link);
      const sourceDetails = node('details', 'entry-details');
      sourceDetails.append(node('summary', '', 'Source notes and edition details'));
      for (const note of Array.isArray(item.source_notes) ? item.source_notes : []) {
        if (typeof note?.text !== 'string') continue;
        sourceDetails.append(node('p', 'commentary-excerpt', note.text));
        if (validUrl(note.source_url)) { const noteLink = safeLink(note.source_url, 'Source note'); if (noteLink) sourceDetails.append(noteLink); }
      }
      if (typeof item.license === 'string') sourceDetails.append(node('p', 'candidate-reason', item.license));
      sourceDetails.append(node('pre', 'passage-analysis-receipt', JSON.stringify({
        comparison_id: item.comparison_id, campbell_record_id: wrapper.campbell_record_id,
        scope: item.scope, selection_aligned: false, exact_edition_alignment: false,
        reuse_status: item.reuse_status, source_provenance: item.source_provenance,
        edition_difference_metadata: item.edition_difference_metadata,
      }, null, 2)));
      card.append(sourceDetails); panel.append(card);
    }
    host.append(panel); return true;
  }
  function rankingCandidateLabel(candidate) {
    if (!candidate) return '';
    const labels = { pofs: 'part of speech', gend: 'gender', num: 'number', pers: 'person', dial: 'dialect', decl: 'declension', stemtype: 'stem type' };
    const literal = value => typeof value === 'string' || typeof value === 'number' ? String(value)
      : Array.isArray(value) ? value.map(literal).filter(Boolean).join(', ')
      : value && typeof value === 'object' && Object.hasOwn(value, '$') ? literal(value.$) : '';
    const fields = value => Object.entries(value || {}).filter(([, raw]) => literal(raw)).map(([key, raw]) => `${labels[key] || key}: ${literal(raw)}`);
    const parts = [candidate.lemma || candidate.matched_form || 'Unlabelled candidate'];
    const analysis = candidate.analysis_text || candidate.analysis;
    if (analysis) parts.push(typeof analysis === 'string' ? analysis : JSON.stringify(analysis));
    const inflection = fields({ ...candidate.inflection, ...candidate.features });
    if (inflection.length) parts.push(inflection.join(' · '));
    const dictionary = Object.fromEntries(Object.entries(candidate.dictionary_fields || {}).filter(([key]) => !['hdwd', 'lang'].includes(key)));
    const dictionaryText = fields(dictionary);
    if (dictionaryText.length) parts.push(`Dictionary fields: ${dictionaryText.join(' · ')}`);
    if (candidate.equivalent_form) parts.push(`Source equivalent form: ${candidate.equivalent_form}`);
    if (parts.length === 1) parts.push('Grammatical analysis not supplied');
    return parts.join(' · ');
  }
  function lexicalPrediction(token) {
    return token?.prediction_status !== 'not_applicable' && !['whitespace', 'editorial', 'punctuation'].includes(token?.token_kind)
      && /[\p{L}\p{N}]/u.test(String(token?.text || ''));
  }
  function structuredSensesPresent(value) {
    return value && (Object.hasOwn(value, 'dictionary_senses') || Object.hasOwn(value, 'dictionary_senses_status'));
  }
  function literalSenses(value) {
    const id = value.gloss_entry_id || value.id;
    return (Array.isArray(value.dictionary_senses) ? value.dictionary_senses : []).filter(sense => sense?.id && sense.evidence_type === 'dictionary_sense'
      && englishTranslation(sense) && typeof sense.text === 'string' && sense.text.trim()
      && (sense.lexicon_entry_id || sense.entry_id) === id && sense.source_url);
  }
  function glossBasis(gloss) {
    return gloss?.selection_basis === 'jev_contextual_sense_proposal'
      ? 'Contextual meaning proposed by Jev; not verified'
      : 'Dictionary source order; contextual meaning not selected';
  }
  // Slice the original selection, never reconstruct its punctuation or spacing
  // from parser tokens. Bad offsets lose annotations, not source characters.
  function interlinearSegments(selection, reading) {
    const text = String(selection?.text || ''), start = selection?.start_utf16;
    if (!Number.isInteger(start)) return [{ text }];
    const words = (reading?.tokens || []).filter(token => token.kind === 'word')
      .slice().sort((a, b) => a.start_utf16 - b.start_utf16);
    const segments = []; let cursor = 0;
    for (const token of words) {
      const low = token.start_utf16 - start, high = token.end_utf16 - start;
      if (!Number.isInteger(low) || !Number.isInteger(high) || low < cursor || high <= low || high > text.length
        || text.slice(low, high) !== token.text) continue;
      if (low > cursor) segments.push({ text: text.slice(cursor, low) });
      segments.push({ text: text.slice(low, high), token }); cursor = high;
    }
    if (cursor < text.length) segments.push({ text: text.slice(cursor) });
    return segments;
  }
  function renderInterlinear(host, data, node) {
    const interlinear = data.interlinear;
    const readings = interlinear?.text === data.selection?.text ? interlinear.readings || [] : [];
    if (!readings.length) return false;
    const content = node('div', 'interlinear-content');
    const renderReading = reading => {
      content.replaceChildren();
      const groups = new Map((reading.groups || []).map((group, index) => [group.id, {
        ...group, key: index < 26 ? String.fromCharCode(65 + index) : String(index + 1), color: index < 4 ? index : 'neutral'
      }]));
      const phrase = node('div', 'interlinear-phrase');
      phrase.setAttribute('aria-label', 'Greek with dictionary glosses and proposed parsing');
      for (const segment of interlinearSegments(data.selection, reading)) {
        const token = segment.token;
        if (!token) {
          const literal = node('span', 'interlinear-literal', segment.text); literal.setAttribute('lang', 'grc');
          phrase.append(literal); continue;
        }
        const proposedGroup = groups.get(token.agreement_group_id);
        const group = proposedGroup?.token_ids?.includes(token.token_id) ? proposedGroup : null;
        const word = node('span', `interlinear-word${group ? ` interlinear-agreement-${group.color}` : ''}`);
        word.setAttribute('data-token-id', token.token_id || '');
        if (group) word.setAttribute('data-agreement-group', group.id);
        const greek = node('span', 'interlinear-greek', segment.text); greek.setAttribute('lang', 'grc');
        const glossText = token.gloss?.status === 'available' && typeof token.gloss.text === 'string' ? token.gloss.text.trim() : '';
        const gloss = node('strong', 'interlinear-gloss', glossText || '—'); gloss.setAttribute('lang', 'en');
        if (!glossText) gloss.setAttribute('aria-label', 'English dictionary meaning unavailable');
        else gloss.title = `${token.gloss.full_text || glossText} — ${glossBasis(token.gloss)}`;
        const parse = node('span', 'interlinear-parse', token.parse_short || '—');
        if (!token.parse_short) parse.setAttribute('aria-label', 'Parsing unavailable');
        if (token.form && token.form !== token.text) {
          // The editor's reading of a bracket-interrupted or underdotted word.
          const supplied = (token.supplied_letters || []).join(', ');
          greek.title = `Editor's reading: ${token.form}${supplied ? ` (supplied: ${supplied})` : ''}`;
          greek.classList.add('interlinear-reconstructed');
        }
        word.append(greek, gloss, parse);
        if (group) {
          const key = node('span', 'interlinear-group-key', group.key);
          key.setAttribute('aria-label', `Proposed agreement group ${group.key}: ${group.label}`);
          word.append(key);
        }
        phrase.append(word);
      }
      content.append(phrase);
      if (groups.size) {
        const legend = node('div', 'interlinear-legend'); legend.setAttribute('aria-label', 'Proposed agreement groups');
        for (const group of groups.values()) {
          const item = node('span', `interlinear-legend-item interlinear-agreement-${group.color}`, `Group ${group.key} · ${group.label}`);
          item.setAttribute('data-agreement-group', group.id); legend.append(item);
        }
        content.append(legend);
      }
      const evidence = node('details', 'entry-details interlinear-evidence');
      evidence.append(node('summary', '', 'About this reading'));
      evidence.append(node('p', 'candidate-reason', 'Short dictionary glosses are not a phrase translation or a verified contextual sense. Colours and group letters show proposed grammatical agreement, not simply matching endings.'));
      const receipt = node('pre', 'passage-analysis-receipt', JSON.stringify({ reading, warnings: interlinear.warnings || [] }, null, 2));
      evidence.append(receipt); content.append(evidence);
    };
    // Only server-supplied coherent readings are offered. Per-word alternatives
    // are not multiplied into imaginary phrase interpretations here.
    if (readings.length > 1) {
      const label = node('label', 'interlinear-reading-picker', 'Reading ');
      const select = node('select'); select.setAttribute('aria-label', 'Proposed phrase reading');
      for (const [index, reading] of readings.entries()) {
        const option = node('option', '', reading.label || `Reading ${index + 1}`); option.value = String(index); select.append(option);
      }
      select.addEventListener('change', () => renderReading(readings[Number(select.value)] || readings[0]));
      label.append(select); host.append(label);
    }
    host.append(content); renderReading(readings[0]); return true;
  }
  function sourceCandidateGroups(token) {
    const groups = { exact: [], nearby: [], other: [] };
    for (const item of token.source_candidates || []) {
      const form = item.matched_form || item.attested_form;
      if (token.analysis_match_status === 'spelling_suggestions_only' || Number(item.edit_distance) > 0) groups.nearby.push(item);
      else if (form && form.normalize('NFC') === (token.form || token.text).normalize('NFC')) groups.exact.push(item);
      else groups.other.push(item);
    }
    return groups;
  }
  function selectionIssue(span) {
    if (!span?.selected_text?.trim()) return 'Select source text to analyze.';
    if ([...span.selected_text].length > MAX_CHARACTERS) return 'Analyze up to 2,000 characters at a time. The selection has not been shortened.';
    if ((span.selected_text.match(/[\p{L}\p{M}]+(?:['’᾽ʼ᾿][\p{L}\p{M}]+)*/gu) || []).length > MAX_WORDS) return 'Analyze up to 80 words at a time. The selection has not been shortened.';
    return '';
  }
  function sourceMap(root, source) {
    const map = new WeakMap();
    const blocks = [...root.querySelectorAll('.line-content, p')];
    let cursor = 0;
    for (const block of blocks) {
      const text = block.textContent;
      const start = source.indexOf(text, cursor);
      if (start < 0 || source.slice(cursor, start).trim()) return null;
      const walker = root.ownerDocument.createTreeWalker(block, 4);
      let offset = start;
      while (walker.nextNode()) {
        const leaf = walker.currentNode;
        map.set(leaf, { start: offset, end: offset + leaf.data.length });
        offset += leaf.data.length;
      }
      cursor = start + text.length;
    }
    return blocks.length && !source.slice(cursor).trim() ? map : null;
  }
  function selectedSpan(selection, root, map, source) {
    if (!map || selection?.rangeCount !== 1) return null;
    const range = selection.getRangeAt(0);
    if (range.collapsed || !root.contains(range.startContainer) || !root.contains(range.endContainer)) return null;
    const walker = root.ownerDocument.createTreeWalker(root, 4);
    let start = null, end = null;
    while (walker.nextNode()) {
      const leaf = walker.currentNode, mapped = map.get(leaf);
      if (!mapped || !range.intersectsNode(leaf)) continue;
      const low = leaf === range.startContainer ? range.startOffset : 0;
      const high = leaf === range.endContainer ? range.endOffset : leaf.data.length;
      if (low >= high) continue;
      if (start === null) start = mapped.start + low;
      end = mapped.start + high;
    }
    return start === null ? null : { start, end, offset_unit: 'utf16', selected_text: source.slice(start, end) };
  }
  function createRequester({ post, current, onResult, onError, onBusy }) {
    let generation = 0, controller = null;
    function cancel() { ++generation; controller?.abort(); controller = null; onBusy(false); }
    async function run(body) {
      cancel();
      const ticket = generation, requestController = new AbortController();
      controller = requestController; onBusy(true);
      try {
        const data = await post('/api/analyze-passage', body, { signal: requestController.signal });
        if (ticket !== generation || !current(body)) return;
        if (data.passage?.id !== body.passage_id || data.selection?.text !== body.selected_text
          || data.selection?.start_utf16 !== body.start || data.selection?.end_utf16 !== body.end) {
          throw new Error('The service returned a different passage or selection. Select the text again.');
        }
        onResult(data);
      } catch (error) {
        if (ticket === generation && current(body) && error.name !== 'AbortError') onError(error);
      } finally {
        if (ticket === generation) { controller = null; onBusy(false); }
      }
    }
    return { cancel, run };
  }
  function mount({ root, toolbar, selectionHost, onSelectionChange, getPassage, post, node, safeLink, inspectWord }) {
    const startPhrase = node('button', 'selection-start', 'Select phrase'); startPhrase.type = 'button';
    startPhrase.setAttribute('aria-pressed', 'false'); startPhrase.setAttribute('aria-controls', root.id || 'passage-text');
    (selectionHost || toolbar).append(startPhrase);
    const analyze = node('button', 'selection-analyze', 'Analyze selection'); analyze.type = 'button';
    toolbar.prepend(analyze);
    const extend = node('button', 'selection-extend', 'Choose end word'); extend.type = 'button';
    extend.title = 'Select a start word, activate this control, then tap or focus and activate the last word.';
    extend.setAttribute('aria-pressed', 'false'); toolbar.append(extend);
    const selectionNote = node('small', 'selection-analysis-note'); selectionNote.setAttribute('role', 'status'); toolbar.append(selectionNote);
    const clearSelection = node('button', 'selection-clear', 'Clear selection'); clearSelection.type = 'button'; toolbar.append(clearSelection);
    toolbar.setAttribute('role', 'region'); toolbar.setAttribute('aria-label', 'Selected text actions');
    const panel = node('section', 'passage-analysis'); panel.hidden = true;
    panel.setAttribute('aria-label', 'Selected passage analysis');
    toolbar.after(panel);
    const heading = node('div', 'passage-analysis-heading');
    const title = node('h3', '', 'Selection analysis');
    const close = node('button', 'passage-analysis-close', 'Collapse analysis'); close.type = 'button';
    heading.append(title, close);
    const quote = node('blockquote', 'passage-analysis-selection');
    const controls = node('div', 'passage-analysis-controls');
    const machine = node('button', '', 'More possible parses'); machine.type = 'button';
    const rerank = node('button', '', 'Ask Jev to rank parses and meanings'); rerank.type = 'button';
    const cancel = node('button', '', 'Cancel request'); cancel.type = 'button'; cancel.hidden = true;
    controls.append(machine, rerank, cancel);
    const status = node('p', 'candidate-reason'); status.setAttribute('role', 'status');
    const output = node('div', 'passage-analysis-output');
    const advanced = node('details', 'entry-details passage-analysis-advanced');
    advanced.append(node('summary', '', 'Analysis options'), controls);
    panel.append(heading, quote, status, output, advanced);
    let map = null, source = '', span = null, wordMode = false, busy = false, passageId = '', extending = false, includeMachine = false;
    let phrasePhase = '', gesture = null, moved = false;
    // Observe gestures without cancelling browser scrolling or native selection.
    root.addEventListener('pointerdown', event => { gesture = { x: event.clientX, y: event.clientY, id: event.pointerId }; moved = false; }, { passive: true });
    root.addEventListener('pointermove', event => {
      if (gesture && gesture.id === event.pointerId && Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) > 10) moved = true;
    }, { passive: true });
    root.addEventListener('pointercancel', () => { moved = true; gesture = null; }, { passive: true });
    const key = value => value ? `${value.start}:${value.end}:${value.selected_text}` : '';
    const requester = createRequester({ post,
      current: body => getPassage()?.id === body.passage_id && key(body) === key(span),
      onBusy(value) { busy = value; status.classList[value ? 'add' : 'remove']('melos-loading'); cancel.hidden = !value; panel.setAttribute('aria-busy', String(value)); refreshAction(); machine.disabled = value; rerank.disabled = value; },
      onError(error) {
        status.textContent = 'Could not load this analysis. Try again, or look up a word.';
        const detail = node('details', 'entry-details notice-details');
        detail.append(node('summary', '', 'Details'), node('p', 'candidate-reason', String(error.message || error)));
        output.append(detail);
      },
      onResult(data) { status.textContent = ''; render(data); }
    });
    function say(host, text, cls = 'candidate-reason') { if (text) host.append(node('p', cls, text)); }
    function details(host, label, data) {
      const box = node('details', 'entry-details');
      box.append(node('summary', '', label), node('pre', 'passage-analysis-receipt', JSON.stringify(data, null, 2))); host.append(box);
    }
    function link(host, url, label) { const item = safeLink(url, label); if (item) host.append(item); }
    function section(label, collapsed = false) { const part = node(collapsed ? 'details' : 'section', 'passage-analysis-section'); part.append(node(collapsed ? 'summary' : 'h4', '', label)); output.append(part); return part; }
    function featureText(value) {
      if (!value) return '';
      return typeof value === 'string' ? value : Object.entries(value).map(([name, field]) => `${name}: ${typeof field === 'string' ? field : JSON.stringify(field)}`).join(' · ');
    }
    function candidate(host, value, label, index, showLemma = true, suppressLegacyGloss = false) {
      const card = node('div', 'candidate');
      if (showLemma) say(card, value.lemma || 'Headword not supplied', 'candidate-lemma');
      say(card, value.analysis_text || featureText(value.features) || featureText(value.inflection) || value.analysis || 'Inflection not supplied.', 'candidate-analysis');
      const glosses = suppressLegacyGloss ? [] : structuredSensesPresent(value) ? literalSenses(value).map(sense => sense.text)
        : value.glosses || (value.gloss ? [value.gloss] : []);
      for (const gloss of [...new Set(glosses)]) say(card, gloss, 'candidate-gloss');
      renderPartialCandidateEvidence(card, value, node);
      details(card, 'Sources and analysis details', { category: label, ...value }); host.append(card);return card;
    }
    function render(data) {
      output.replaceChildren();
      const syntaxTokens = data.syntax?.tokens || [];
      const words = (data.tokens || []).filter(token => token.kind === 'word');
      const hasReading = data.interlinear?.text === data.selection?.text && data.interlinear?.readings?.length;
      const readingTokens = hasReading ? data.interlinear.readings[0].tokens || [] : [];
      quote.hidden = Boolean(hasReading);
      if (hasReading) renderInterlinear(section('Proposed reading'), data, node);
      if (words.length > 1) {
        const overview = data.meaning || data.overview || {};
        const exact = (overview.interpretations || []).filter(item => englishTranslation(item) && item.selection_aligned === true);
        if (exact.length) {
          const meaning = section('Phrase meaning');
          for (const item of exact) {
            say(meaning, item.text, 'translation-text');
            details(meaning, 'Translation source and interpretation', item);
          }
        }
      }
      renderPublishedCommentary(output, data, node);
      renderTranslationComparisons(output, data, node, safeLink);
      if (data.editorial_analysis) {
        const host = node('div','editorial-analysis-host'); output.append(host);
        const loaded = getPassage(), selectedKey = key(span);
        renderEditorialAnalysis(host,data,loaded,node,safeLink,selectSourceSpan,
          () => getPassage() === loaded && key(span) === selectedKey && output.contains(host)).catch(() => {});
      }
      const tokenHost = section(words.length > 1 ? 'Word by word' : 'Meaning and possible parses');
      if (!words.length) say(tokenHost, 'No analyzable words in this literal selection. Editorial signs remain preserved above.');
      for (const token of words) {
        const box = node('details', 'passage-analysis-token'); box.open = words.length === 1;
        const recorded = sourceCandidateGroups(token), contextual = token.contextual_candidates || [], computed = token.machine?.machine_candidates || [];
        const alternatives = dedupeCandidates([...recorded.exact, ...contextual, ...computed]);
        const displayAlternatives = groupCandidateDisplays(alternatives);
        const projection = readingTokens.find(item => (item.token_id === token.id || item.token_id === token.token_id)
          && item.text === token.text && item.start_utf16 === token.start_utf16 && item.end_utf16 === token.end_utf16);
        const structured = (token.lexicon_entries || []).some(structuredSensesPresent) || alternatives.some(structuredSensesPresent)
          || Object.hasOwn(projection?.gloss || {}, 'alternatives');
        const shortGloss = projection?.gloss?.status === 'available' ? projection.gloss.text
          : structured ? '' : alternatives.find(item => item.gloss)?.gloss;
        const reading = token.form && token.form !== token.text ? ` (read ${token.form})` : '';
        box.append(node('summary', '', `${token.text}${reading}${shortGloss ? ` — ${shortGloss}` : ''} · ${displayAlternatives.length} ${displayAlternatives.length === 1 ? 'parse' : 'possible parses'}`));
        const lookup = node('button', 'occurrence-search', 'Open word dictionary'); lookup.type = 'button';
        lookup.addEventListener('click', () => inspectWord(token.form || token.text)); box.append(lookup);
        if (token.editorial_reconstruction || token.uncertain_letters) {
          say(box, token.editorial_reconstruction
            ? `Letters in square brackets were supplied by the editor${(token.supplied_letters || []).length ? ` (${token.supplied_letters.join(', ')})` : ''}; the analysis follows the printed reading ${token.form}.`
            : 'Underdots mark doubtfully read letters; the analysis follows the printed reading.', 'candidate-reason');
        }
        const ranking = projection?.morphology_ranking || [];
        if (ranking.length) {
          // Full parses in order of fit to the contextual prediction and to the
          // predicted agreeing words. The order is a proposal; all stay listed.
          const ranked = node('div', 'passage-ranked-parses');
          say(ranked, `Parses ranked by fit to the context · ${String(projection.selection_basis || '').replaceAll('_', ' ')}`, 'candidate-meta-label');
          ranking.slice(0, 6).forEach((item, index) => {
            const row = node('div', 'passage-ranked-parse');
            const chosen = projection.candidate_id === item.candidate_id
              || (projection.supporting_parse_candidate_ids || []).includes(item.candidate_id);
            row.append(node('span', 'ranked-index', `${index + 1}.`), node('strong', 'candidate-analysis', item.parse_short || '—'),
              node('span', 'candidate-lemma', item.lemma || ''));
            const basis = item.basis === 'machine_analysis_normalised'
              ? `via ${item.normalised_query} (${String(item.normalisation_rule || '').replaceAll('_', ' ')})`
              : String(item.basis || '').replaceAll('_', ' ');
            say(row, [basis, chosen ? 'shown above' : null].filter(Boolean).join(' · '), 'candidate-reason');
            ranked.append(row);
          });
          box.append(ranked);
        }
        const variants = token.partial_word || token.editorial_fragment ? [] : window.MelosDictionaryPreview?.lexicalVariantPreview?.(token.form || token.text,
          token.lexical_variants, token.lexical_variant_supporting_claims) || [];
        for (const variant of variants) {
          const card = node('div', 'passage-dictionary-senses');
          say(card, `Dictionary-listed variant: ${variant.form} → ${variant.lemma}`, 'candidate-meta-label');
          for (const meaning of variant.meanings) {
            say(card, meaning.text, 'candidate-gloss'); link(card, meaning.source_url, 'Dictionary source');
          }
          say(card, 'General dictionary meanings; not a resolved inflection or contextual translation.', 'candidate-reason');
          details(card, 'Variant spelling and source evidence', variant.evidence); box.append(card);
        }
        const boundEntryIds = new Set(alternatives.flatMap(item => [item.gloss_entry_id, ...(item.lexicon_entry_ids || [])]).filter(Boolean));
        const senseAlternatives = projection?.gloss?.alternatives || [
          ...alternatives.flatMap(literalSenses),
          ...(token.lexicon_entries || []).filter(entry => boundEntryIds.has(entry.id)).flatMap(literalSenses)
        ];
        if (senseAlternatives.length) {
          const senses = node('div', 'passage-dictionary-senses');
          say(senses, glossBasis(projection?.gloss), 'candidate-meta-label');
          const ranking = (data.sense_ranking?.items || []).find(item => item.token_id === token.id);
          const order = new Map((ranking?.ranked_senses || []).map((item, index) => [item.sense_id, index]));
          const seen = new Set(); let remaining = null;
          for (const sense of senseAlternatives.slice().sort((a, b) => (order.get(a.id) ?? Infinity) - (order.get(b.id) ?? Infinity))) {
            if (!sense?.id || seen.has(sense.id) || !englishTranslation(sense) || !sense.text) continue;
            seen.add(sense.id);
            const row = node('div', 'passage-dictionary-sense'); row.setAttribute('data-sense-id', sense.id);
            const chosen = projection?.gloss?.sense_id === sense.id;
            row.append(node('strong', 'candidate-gloss', sense.text));
            say(row, [sense.source, chosen ? projection.gloss.selection_basis === 'jev_contextual_sense_proposal' ? 'Proposed for this context' : 'Shown above · source order' : null].filter(Boolean).join(' · '));
            const provenance = node('details', 'entry-details'); provenance.append(node('summary', '', 'Dictionary source and scope'));
            if (sense.scope_text && sense.scope_text !== sense.text) say(provenance, sense.scope_text);
            link(provenance, sense.source_url, 'Open dictionary source');
            provenance.append(node('pre', 'passage-analysis-receipt', JSON.stringify(sense, null, 2))); row.append(provenance);
            if (seen.size <= 3) senses.append(row);
            else {
              if (!remaining) { remaining = node('details', 'entry-details'); remaining.append(node('summary', '', 'More dictionary meanings')); senses.append(remaining); }
              remaining.append(row);
            }
          }
          box.append(senses);
        }
        const lemmas = new Map();
        for (const item of displayAlternatives) {
          const lemmaKey = `${item.lemma || ''}:${item.homograph_id || item.lemma_identity || ''}`;
          if (!lemmas.has(lemmaKey)) {
            const group = node('div', 'passage-lemma-group');
            say(group, item.lemma || 'Headword not supplied', 'candidate-lemma');
            lemmas.set(lemmaKey, group); box.append(group);
          }
          const card=candidate(lemmas.get(lemmaKey), item, 'Source and computational alternatives; see individual evidence rows', 0, false, structured);
          if(item.basis==='machine_analysis' && data.machine_subentry_evidence) {
            const loaded=getPassage(),selectedKey=key(span);
            renderMachineSubentryMeanings(card,data,token,item,node,safeLink,
              ()=>getPassage()===loaded && key(span)===selectedKey && output.contains(card)).catch(()=>{});
          }
        }
        const technical = node('details', 'entry-details passage-token-evidence');
        technical.append(node('summary', '', 'Evidence and contextual prediction')); box.append(technical);
        say(technical, token.candidate_scope);
        for (const predicted of syntaxTokens.filter(item => lexicalPrediction(item) && item.start_utf16 === token.start_utf16 && item.end_utf16 === token.end_utf16 && item.text === token.text)) {
          const model = node('div', 'candidate passage-model-prediction');
          say(model, 'Contextual model prediction · exact token span', 'candidate-meta-label');
          say(model, predicted.lemma || 'Model headword unavailable', 'candidate-lemma');
          say(model, [predicted.upos, predicted.xpos, featureText(predicted.features)].filter(Boolean).join(' · '), 'candidate-analysis');
          say(model, 'One contextual parser prediction, not a verified source parse.');
          say(model, [data.syntax.provider, data.syntax.model, data.syntax.model_version].filter(Boolean).join(' · '));
          details(model, 'Model token and provenance', { token: predicted, provenance: data.syntax.provenance }); technical.append(model);
        }
        for (const [items, title, label] of [
          [recorded.other, 'Other source-form matches', 'Other source spelling · not an exact match'],
          [recorded.nearby, 'Nearby spellings · not parses of this word', 'Nearby spelling—not a parse of this word']
        ]) if (items.length) {
          const suggestions = node('details', 'entry-details passage-spelling-suggestions');
          suggestions.append(node('summary', '', `${title} · ${items.length}`));
          say(suggestions, 'The analyses below belong to the displayed source spellings. They must not be read as parses of the selected word.');
          items.forEach((item, i) => candidate(suggestions, item, label, i)); box.append(suggestions);
        }
        for (const warning of token.warnings || []) say(technical, warning);
        if (token.machine?.receipt) details(technical, 'Computational provider receipt', token.machine.receipt);
        if (token.structured_evidence?.claims?.length) details(technical, 'Recorded evidence and exact application scope', { evidence: token.structured_evidence, claim_applications: token.claim_applications });
        if (token.contextual_supporting_claims?.length) details(technical, 'Contextual claims and application scope', { claims: token.contextual_supporting_claims, claim_applications: token.claim_applications });
        tokenHost.append(box);
      }
      const syntax = section('Syntax and relationships', true);
      say(syntax, `Contextual parser: ${String(data.syntax?.status || 'unavailable').replaceAll('_', ' ')}. Proposed attachments are model output, not source annotations.`);
      say(syntax, data.syntax?.scope === 'whole_passage' ? 'The parser reads the containing passage; relationships below concern the selected words. Heads may lie outside the selection.' : 'The parser reads the selected span; relationships outside this context may be missing.');
      const relationships = syntaxTokens.filter(token => token.selected !== false && lexicalPrediction(token)).map(token => {
        const head = syntaxTokens.find(item => item.id === token.head && item.sentence_id === token.sentence_id);
        const unresolved = token.attachment_status === 'unresolved_nonlexical_head' || (head && !lexicalPrediction(head));
        return { dependent_text: token.text, head_text: unresolved ? 'unresolved attachment to nonlexical material'
          : token.head == null ? 'root' : head?.text || `unresolved head ${token.head}`, relation: unresolved ? 'uncertain' : token.deprel };
      });
      for (const relation of relationships) say(syntax, `${relation.dependent_text || relation.dependent || relation.token_id || '?'} → ${relation.head_text || relation.head || 'root'} · ${relation.relation || relation.deprel || 'unspecified relationship'}`, 'passage-syntax-link');
      if (data.syntax) details(syntax, 'Parser relationships and provenance', data.syntax);
      for (const warning of data.lint?.warnings || []) say(syntax, typeof warning === 'string' ? warning : warning.message || JSON.stringify(warning));
      const ranking = section('Contextual ranking', true);
      say(ranking, `Jev: ${String(data.ranking?.status || 'not_requested').replaceAll('_', ' ')}. Probabilities are model estimates, not verified correctness rates. All original alternatives remain available above.`);
      for (const item of data.ranking?.items || []) {
        say(ranking, `${item.form || item.token_id} · ${String(item.status || 'unavailable').replaceAll('_', ' ')}`, 'candidate-meta-label');
        const candidates = item.decision?.packet?.candidates || [];
        for (const [index, ranked] of (item.ranked_candidates || []).entries()) {
          const identified = candidates.find(candidate => (candidate.id || candidate.candidate_id) === ranked.candidate_id);
          const score = typeof ranked.score_uncalibrated === 'number' && Number.isFinite(ranked.score_uncalibrated) && ranked.score_uncalibrated >= 0 && ranked.score_uncalibrated <= 1
            ? ` · ${(ranked.score_uncalibrated * 100).toFixed(1)}% model estimate` : '';
          const rankedRow = node('p', 'candidate-analysis passage-ranking-candidate', `${index + 1}. ${rankingCandidateLabel(identified) || ranked.candidate_id}${score}`);
          rankedRow.title = `Candidate ID: ${ranked.candidate_id}`; ranking.append(rankedRow);
        }
        const abstain = item.decision?.model_probabilities_uncalibrated?.abstain;
        if (typeof abstain === 'number' && Number.isFinite(abstain) && abstain >= 0 && abstain <= 1) say(ranking, `Abstain · ${(abstain * 100).toFixed(1)}% model estimate`, 'candidate-analysis passage-ranking-abstain');
        say(ranking, item.decision?.reason);
      }
      for (const warning of data.ranking?.warnings || []) say(ranking, warning);
      if (data.ranking && data.ranking.status !== 'not_requested') details(ranking, 'Ranking estimates and provenance', data.ranking);
      if (data.sense_ranking) {
        say(ranking, `Dictionary meanings: ${String(data.sense_ranking.status || 'not_requested').replaceAll('_', ' ')}. Sense ranking is separate from morphological ranking; it does not verify a translation.`);
        details(ranking, 'Meaning ranking estimates and provenance', data.sense_ranking);
      }
      const context = data.context || {}, translations = section('English translation of the containing passage', true);
      say(translations, 'Whole containing passage unless explicit selection alignment is supplied. This is not an exact translation of the selected phrase.');
      const english = (context.published_translations || []).filter(englishTranslation);
      if (!english.length) say(translations, 'No published English translation linked to this passage.');
      for (const item of english) {
        say(translations, [item.author || item.translator, item.work, item.citation, item.source].filter(Boolean).join(' · ') || 'Linked published translation', 'translation-credit');
        say(translations, item.text || item.preview_text || item.excerpt, 'translation-text');
        link(translations, item.source_url, 'Open published translation source');
        details(translations, 'Translation scope and provenance', item);
      }
      const evidence = section('Commentary, dialect and sources', true);
      for (const warning of data.warnings || []) say(evidence, warning);
      say(evidence, 'Authorial dialect is a contextual prior; it does not establish that every form is exclusive to that dialect.');
      if (!context.commentary?.length) say(evidence, 'No linked commentary supplied.');
      for (const item of context.commentary || []) {
        say(evidence, [item.author, item.work, item.citation].filter(Boolean).join(' · '), 'translation-credit');
        say(evidence, item.text || item.excerpt || item.preview_text, 'commentary-excerpt');
        link(evidence, item.source_url, 'Open commentary source'); details(evidence, 'Commentary scope and provenance', item);
      }
      if (context.author_profile) details(evidence, 'Authorial dialect prior and source', context.author_profile);
      if (context.structured_evidence?.claims?.length) details(evidence, 'Recorded passage evidence', context.structured_evidence);
      else say(evidence, 'No structured passage annotation supplied.');
    }
    function refreshAction() {
      const issue = !map ? 'This displayed text cannot be mapped exactly to the original passage.' : selectionIssue(span);
      analyze.disabled = busy || Boolean(issue) || phrasePhase === 'end'; analyze.title = issue || 'Analyze this exact source span; Jev ranking requires a separate action.';
      extend.disabled = !span || !map;
      startPhrase.disabled = !map || !root.querySelector('.word');
      startPhrase.setAttribute('aria-pressed', String(Boolean(phrasePhase)));
      startPhrase.textContent = phrasePhase ? 'Start a new phrase' : 'Select phrase';
      clearSelection.disabled = false;
      clearSelection.textContent = phrasePhase ? 'Cancel selection' : 'Clear selection';
      selectionNote.textContent = phrasePhase === 'start' ? 'Tap the first word. You can scroll between taps.'
        : phrasePhase === 'end' ? 'Tap the last word, or tap the first word again for one word.'
          : issue || (phrasePhase === 'ready' ? 'Phrase selected. Analyze it or start a new phrase.' : '');
      selectionNote.hidden = !selectionNote.textContent;
      if (phrasePhase) toolbar.hidden = false;
    }
    function highlight() {
      for (const button of root.querySelectorAll('.word')) {
        const walker = root.ownerDocument.createTreeWalker(button, 4); let selected = false;
        while (walker.nextNode()) {
          const item = map?.get(walker.currentNode);
          if (span && item && item.start < span.end && item.end > span.start) selected = true;
        }
        button.classList[selected ? 'add' : 'remove']('phrase-selected');
      }
    }
    function change(next, word = false) {
      wordMode = word;
      if (key(next) !== key(span)) { requester.cancel(); includeMachine = false; panel.hidden = true; quote.hidden = false; output.replaceChildren(); }
      span = next; highlight(); refreshAction();
    }
    function selectSourceSpan(next, analyzeNow = false) {
      if (!map || getPassage()?.id !== passageId || getPassage()?.text !== source
        || next?.offset_unit !== 'utf16' || !Number.isInteger(next.start) || !Number.isInteger(next.end)
        || next.start < 0 || next.end <= next.start || next.end > source.length
        || next.selected_text !== source.slice(next.start,next.end) || selectionIssue(next)) return false;
      phrasePhase = ''; extending = false; extend.setAttribute('aria-pressed','false');
      window.getSelection?.()?.removeAllRanges?.(); change({...next},true);
      toolbar.hidden = false; onSelectionChange?.();
      if (analyzeNow) request({fetch_machine:false,rerank:false});
      return true;
    }
    function request(options = {}) {
      if (!span || selectionIssue(span) || !map || !getPassage()?.id) return;
      panel.hidden = false; quote.hidden = false; quote.textContent = span.selected_text;
      if (options.fetch_machine) includeMachine = true;
      status.textContent = options.rerank ? 'Requesting Jev model estimates…' : 'Looking up this exact selection…';
      requester.run({ version: 1, passage_id: getPassage().id, ...span, fetch_machine: includeMachine, rerank: false, ...options });
      panel.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    }
    analyze.addEventListener('click', () => request());
    startPhrase.addEventListener('click', () => {
      phrasePhase = 'start'; extending = false; extend.setAttribute('aria-pressed', 'false');
      window.getSelection?.()?.removeAllRanges?.();
      change(null); onSelectionChange?.(); refreshAction();
    });
    clearSelection.addEventListener('click', () => {
      phrasePhase = ''; extending = false; extend.setAttribute('aria-pressed', 'false'); extend.textContent = 'Choose end word';
      window.getSelection?.()?.removeAllRanges?.();
      change(null); toolbar.hidden = true; onSelectionChange?.(); startPhrase.focus({ preventScroll: true });
    });
    extend.addEventListener('click', () => {
      window.getSelection?.()?.removeAllRanges?.();
      extending = !extending; extend.setAttribute('aria-pressed', String(extending));
      extend.textContent = extending ? 'Now choose the last word' : 'Choose end word';
      phrasePhase = extending ? 'end' : ''; refreshAction();
    });
    machine.addEventListener('click', () => request({ fetch_machine: true }));
    rerank.addEventListener('click', () => request({ rerank: true }));
    cancel.addEventListener('click', () => { requester.cancel(); status.textContent = 'Request cancelled. A request already received by the service may still finish.'; });
    close.addEventListener('click', () => { requester.cancel(); panel.hidden = true; analyze.focus(); });
    return {
      refreshAction, selectSourceSpan,
      wordSelection: () => wordMode ? span : null,
      currentSelection: () => span,
      isExtending: () => extending,
      isChoosingPhrase: () => Boolean(phrasePhase),
      ignoreClick: event => Boolean(event?.detail && moved),
      hasSelection: () => Boolean(span),
      reset() { requester.cancel(); span = null; map = null; wordMode = false; passageId = ''; extending = false; phrasePhase = ''; gesture = null; moved = false; includeMachine = false; extend.setAttribute('aria-pressed', 'false'); extend.textContent = 'Choose end word'; panel.hidden = true; quote.hidden = false; output.replaceChildren(); highlight(); refreshAction(); },
      bind(passage) { source = String(passage.text || ''); passageId = passage.id; map = sourceMap(root, source); refreshAction(); },
      selectionChanged(selection) {
        if (!getPassage() || getPassage().id !== passageId) return;
        // Focusing the action button collapses native selection in some browsers.
        // Keep the captured range until a new valid source selection replaces it.
        if (!selection || !selection.rangeCount || selection.isCollapsed || selection.getRangeAt?.(0)?.collapsed) return;
        const next = selectedSpan(selection, root, map, source);
        if (next) { phrasePhase = ''; extending = false; extend.setAttribute('aria-pressed', 'false'); extend.textContent = 'Choose end word'; change(next); }
      },
      chooseWord(button) {
        const walker = root.ownerDocument.createTreeWalker(button, 4); let first = null, last = null;
        while (walker.nextNode()) { const item = map?.get(walker.currentNode); if (item) { first ??= item.start; last = item.end; } }
        if ((extending || phrasePhase === 'end') && span && first !== null) { first = Math.min(first, span.start); last = Math.max(last, span.end); }
        if (first !== null && phrasePhase) phrasePhase = phrasePhase === 'end' ? 'ready' : 'end';
        extending = false; extend.setAttribute('aria-pressed', 'false'); extend.textContent = 'Choose end word';
        change(first === null ? null : { start: first, end: last, offset_unit: 'utf16', selected_text: source.slice(first, last) }, true);
        if (span) { toolbar.hidden = false; const selected = toolbar.querySelector('#selected-phrase'); if (selected) selected.textContent = `“${span.selected_text}”`; }
      }
    };
  }
  window.MelosPassageAnalysis = { mount, sourceMap, selectedSpan, selectionIssue, createRequester, lexicalPrediction, sourceCandidateGroups, rankingCandidateLabel, dedupeCandidates, groupCandidateDisplays, renderPartialCandidateEvidence, machineSubentryMeanings, renderMachineSubentryMeanings, englishTranslation, interlinearSegments, renderInterlinear, renderPublishedCommentary, renderTranslationComparisons, verifiedEditorialRows, renderEditorialAnalysis, renderEditorialWordActions };
})();
