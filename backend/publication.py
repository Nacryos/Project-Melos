"""Conservative publication policy; extraction acceptance is not a reuse grant.

The labels below are exact labels in the independently audited local sources.
By default, unknown rights, jurisdiction-only claims, and mixed-rights exports
stay local. The explicit owner-selected source-labels policy disables this filter
without changing the original rights labels or asserting a reuse grant.
This policy never changes the preserved source records or their attribution.
"""
import os
from pathlib import Path
from threading import Lock


_publication_lock = Lock()
_publication_ids = {}


PUBLIC_LICENSES = frozenset({
    'CC-BY-SA-4.0', 'CC-BY-4.0', 'CC BY-SA 4.0', 'CC BY 4.0',
    'Available under a Creative Commons Attribution-ShareAlike 4.0 International License',
    'CC BY-SA 4.0 (repository default; check TEI rights)',
    'PD (ancient text); First1KGreek/Perseus CC BY-SA 4.0',
    'https://creativecommons.org/licenses/by-sa/4.0/',
    'CC BY 3.0', 'CC-BY-SA-3.0-US',
})

PUBLIC_SOURCE_LICENSES = {
    'perseus': frozenset({
        'Available under a Creative Commons Attribution-ShareAlike 4.0 International License',
        'CC BY-SA 4.0 (repository default; check TEI rights)',
        'CC BY-SA 4.0',
    }),
    'p2_perseus': frozenset({'Available under a Creative Commons Attribution-ShareAlike 4.0 International License'}),
    'p2_perseus_notes': frozenset({
        'Available under a Creative Commons Attribution-ShareAlike 4.0 International License',
        'CC BY-SA 4.0 (repository default; check TEI rights)',
    }),
    'reception': frozenset({'CC BY-SA 4.0','https://creativecommons.org/licenses/by-sa/4.0/'}),
    'ogc': frozenset({'CC-BY-4.0','CC-BY-SA-4.0','PD (ancient text); First1KGreek/Perseus CC BY-SA 4.0'}),
    'p2_ogc': frozenset({'CC-BY-4.0','CC-BY-SA-4.0'}),
    'ogc_derived': frozenset({'CC-BY-4.0'}),
    'sappho': frozenset({'CC BY-SA 4.0'}),
    'commentary': frozenset({'CC BY 3.0'}),
    'p2_stesichorus': frozenset({'CC BY 4.0'}),
    'p2_elegy': frozenset({'CC BY-SA 4.0'}),
    'PerseusDL LSJ TEI': frozenset({'CC-BY-SA-4.0'}),
    'PerseusDL Greek Dependency Treebank v1.6': frozenset({'CC-BY-SA-3.0-US'}),
}

EVIDENCE_HOLD = ('Structured evidence is unavailable publicly while record-level '
                 'redistribution rights are reviewed. Local extraction acceptance '
                 'does not establish publication permission.')
WIKTIONARY_HOLD = ('This Kaikki snapshot includes merged fields whose individual '
                   'reuse terms have not been established; public lookup is unavailable.')


def public_deployment():
    return os.environ.get('MELOS_PUBLIC_DEPLOYMENT') == '1'


def publication_restricted():
    """Owner-selected source-labels policy retains original rights notices.

    This bypasses only publication filtering, never extraction acceptance,
    provenance hashes, or the separate public classifier protection.
    Unknown policy values retain the conservative default.
    """
    return public_deployment() and os.environ.get('MELOS_PUBLICATION_POLICY') != 'source-labels'


def record_allowed(record):
    return record.get('license') in PUBLIC_SOURCE_LICENSES.get(record.get('source'), ())


def _snapshot_key(path):
    path = Path(path).resolve()
    stat = path.stat()
    return (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns)


def accepted_ids(connection, path):
    """Scan each immutable corpus snapshot once, including concurrent cold calls.

    The runtime corpus is read-only and replacements are atomic. A changed
    timestamp, size, or file identity invalidates this in-memory decision set.
    A replacement during the scan fails closed instead of caching mixed state.
    """
    with _publication_lock:
        key = _snapshot_key(path)
        if key in _publication_ids:
            return _publication_ids[key]
        ids = frozenset(row[0] for row in connection.execute(
            "SELECT id,source,json_extract(data,'$.license') FROM main.passages"
        ) if row[2] in PUBLIC_SOURCE_LICENSES.get(row[1], ()))
        if _snapshot_key(path) != key:
            raise RuntimeError('Corpus changed while establishing publication permissions; retry.')
        # Bound memory and discard obsolete snapshots, including replacement IDs.
        _publication_ids.clear()
        _publication_ids[key] = ids
        return ids


def corpus_views(connection, path):
    """Shadow source tables only within this read-only request connection."""
    ids = accepted_ids(connection, path)
    connection.create_function('published_id', 1, ids.__contains__, deterministic=True)
    connection.execute('CREATE TEMP VIEW passages AS SELECT * FROM main.passages WHERE published_id(id)')
    connection.execute('''CREATE TEMP VIEW works AS
        SELECT work_id id,author,work,edition,source,language,count(*) count
        FROM passages GROUP BY work_id''')
