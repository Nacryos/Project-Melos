"""Synthetic projection fixtures; no corpus mutation or embedding calls."""
from backend import server


def test_usage_projection_reuses_owner_aliases_and_preserves_source_identity(monkeypatch):
    labels = ['Ibycus', 'ΙΒΥΚΟΣ', 'Homer', 'homerus-epic', 'scholia-in-homerum',
              'Sappho / Alcaeus', 'Unmapped synthetic author', None]
    records = [{'id': f'synthetic:{i}', 'author': author, 'text': 'αβ γδ',
                'citation': f'Synthetic citation {i}', 'work': 'Synthetic work',
                'parent_id': 'homer-parent'} for i, author in enumerate(labels)]
    monkeypatch.setattr(server, 'search', lambda **kwargs: {'results': records})
    class NoEncoder:
        def vectors_for(self, identifiers):
            raise RuntimeError('Explicitly use local TF-IDF in this test')
    monkeypatch.setattr(server, 'semantic_service', lambda: NoEncoder())
    result = server.usage_space(q='αβ', author='', limit=80)
    assert [point['author'] for point in result['points']] == labels
    assert [point['author_canonical'] for point in result['points']] == [
        'Ibycus', 'Ibycus', 'Homer', 'Homer', 'Scholia on Homer',  # merged by the release O alias table
        'Sappho / Alcaeus', 'Unmapped synthetic author', '']
    for record, point in zip(records, result['points']):
        assert point['citation'] == record['citation']
        assert point['text'] == record['text']
        assert all(isinstance(point[axis], float) for axis in ('x', 'y', 'z'))
        assert 'author_canonical' not in record
