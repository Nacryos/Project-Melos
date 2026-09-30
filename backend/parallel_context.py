"""Discover matching reading texts, without transferring source attestations.

This is a runtime comparison view, never a source claim or a numbering map.
Edition punctuation and editorial signs may differ even when all words match.
"""
import unicodedata

from .textutils import normalize, search_text, tokenize


def comparison_tokens(text):
    return tokenize(search_text(unicodedata.normalize('NFC', str(text or ''))))


def source_claim_matches(claim, source, form):
    """Recheck the original claim's scope/offsets before comparison display."""
    subject=claim.get('subject') or {}
    if (claim.get('status') != 'source_claim' or subject.get('passage_id') != source.get('id')
            or not form
            or unicodedata.normalize('NFC',str(subject.get('form') or '')) != unicodedata.normalize('NFC',form)):
        return False
    start,end=subject.get('start'),subject.get('end')
    if start is not None or end is not None:
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source.get('text') or ''):
            return False
        return unicodedata.normalize('NFC',source['text'][start:end]) == unicodedata.normalize('NFC',form)
    return comparison_tokens(source['text']).count(unicodedata.normalize('NFC',form)) == 1


def matching_texts(form, target, records, author_labels):
    """Require the complete word sequence and one unambiguous token occurrence.

    Do not align by author/title/fragment number alone, or transfer a parse
    from another occurrence of a common word. The original edition record and
    quoted claim remain separately identified in the resulting view.
    """
    if not target or target.get('language') != 'grc' or target.get('kind') != 'text':
        return []
    if target.get('quality') in {'machine_ocr', 'mixed_content', 'needs_review'}:
        return []
    labels = {unicodedata.normalize('NFC', str(name)).casefold() for name in author_labels if name}
    if not labels or labels <= {'unknown', 'anonymous', 'unattributed'}:
        return []
    words = comparison_tokens(target.get('text', ''))
    positions = [i for i, word in enumerate(words) if normalize(word) == normalize(form)]
    if len(words) < 8 or len(positions) != 1:
        return []
    index = positions[0]
    matches = []
    for record in records:
        if record.get('id') == target.get('id'):
            continue
        if (record.get('language') != 'grc' or record.get('kind') != 'text'
                or record.get('quality') in {'machine_ocr', 'mixed_content', 'needs_review'}):
            continue
        if unicodedata.normalize('NFC', str(record.get('author') or '')).casefold() not in labels:
            continue
        other = comparison_tokens(record.get('text', ''))
        # Deliberately retain accents/case. Loose accent-folded similarity is
        # useful for discovery but too weak for this evidence-comparison view.
        if other != words:
            continue
        matches.append({'passage': record, 'alignment': {
            'method': 'Complete NFC search-token sequence matches after punctuation and explicit line-division normalization',
            'matched_words': len(words), 'token_index': index,
            'window': ' '.join(words[max(0,index-4):index+5]),
            'scope': 'Comparison only: editorial signs may differ; no shared witness, numbering equivalence, or direct target annotation is asserted.'}})
    return matches
