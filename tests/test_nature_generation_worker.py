import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import regenerate_nature_image as worker


@pytest.fixture
def gallery(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'GALLERY', tmp_path)
    worker.BATCH_STOP.clear()
    manifest = {'references': ['references/style.png'], 'themes': [{
        'id': 'sea_coast', 'images': [{'id': 'sea_coast-01', 'status': 'pending',
                                     'path': 'images/sea_coast-01.png', 'prompt': 'A quiet sea'}]}]}
    worker.atomic_json(tmp_path / 'manifest.json', manifest)
    return tmp_path


def test_exactly_once_claim(gallery):
    worker.mutate_manifest(lambda m: worker.claim_image(m, 'sea_coast-01'))
    with pytest.raises(ValueError, match='Only pending'):
        worker.mutate_manifest(lambda m: worker.claim_image(m, 'sea_coast-01'))


def test_quota_error_stops_following_requests_and_redacts_key(gallery, monkeypatch):
    monkeypatch.setattr(worker, 'key_environment', lambda: {'OPENAI_API_KEY': 'test-secret'})
    calls = []
    def denied(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1, stdout='', stderr='credit_balance_exhausted test-secret')
    monkeypatch.setattr(worker.subprocess, 'run', denied)
    assert not worker.generate('sea_coast-01')
    assert not worker.generate('another-image-that-must-not-run')
    assert len(calls) == 1
    assert 'test-secret' not in next((gallery / 'logs').glob('*.log')).read_text()
    manifest = worker.read_json(gallery / 'manifest.json')
    assert manifest['generation_blocker'] == 'api_credits_required'
    assert manifest['themes'][0]['images'][0]['status'] == 'failed'


def test_job_path_and_note_validation(gallery):
    outside = gallery / 'outside.json'
    outside.write_text('{}')
    with pytest.raises(ValueError, match='inside'):
        worker.validate_job(outside)
    jobs = gallery / 'jobs'
    jobs.mkdir()
    job = jobs / 'example.json'
    worker.atomic_json(job, {'theme_id': 'sea_coast', 'notes': 'x' * 2001})
    with pytest.raises(ValueError, match='2000'):
        worker.validate_job(job)


def test_retry_appends_once_and_preserves_original(gallery, monkeypatch):
    jobs = gallery / 'jobs'
    jobs.mkdir()
    job = jobs / 'example.json'
    worker.atomic_json(job, {'job_id': 'example', 'theme_id': 'sea_coast',
                            'image_id': 'sea_coast-01', 'notes': 'More waves'})
    called = []
    monkeypatch.setattr(worker, 'generate', lambda image_id: called.append(image_id) or True)
    assert worker.retry_job(job)
    with pytest.raises(FileExistsError):
        worker.retry_job(job)
    images = worker.read_json(gallery / 'manifest.json')['themes'][0]['images']
    assert len(images) == 2 and len(called) == 1
    assert images[0]['prompt'] == 'A quiet sea'
    assert images[1]['prompt'].endswith('More waves')
    assert images[1]['parent_image_id'] == 'sea_coast-01'


def test_manual_cross_process_lock(gallery):
    (gallery / '.manual-generation.lock').write_text('{}')
    with pytest.raises(RuntimeError, match='Another manual generation'):
        worker.retry_job(gallery / 'jobs/unused.json')
    assert (gallery / '.manual-generation.lock').exists()


def test_ready_retry_edits_actual_painting_not_old_references(gallery, monkeypatch):
    (gallery / 'images').mkdir()
    (gallery / 'images/sea_coast-01.png').write_bytes(b'original')
    worker.mutate_manifest(lambda m: worker.find_image(m, 'sea_coast-01').update(status='ready'))
    jobs = gallery / 'jobs'
    jobs.mkdir()
    job = jobs / 'actual-edit.json'
    worker.atomic_json(job, {'theme_id': 'sea_coast', 'image_id': 'sea_coast-01', 'notes': 'Irregular waves'})
    monkeypatch.setattr(worker, 'generate', lambda image_id: True)
    assert worker.retry_job(job)
    images = worker.read_json(gallery / 'manifest.json')['themes'][0]['images']
    assert images[-1]['references'] == ['images/sea_coast-01.png']
    assert 'Irregular waves' in images[-1]['prompt']
    assert 'A quiet sea' not in images[-1]['prompt']
    assert (gallery / 'images/sea_coast-01.png').read_bytes() == b'original'


def test_landscape_snapshots_favourites_without_changing_portraits(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'ROOT', tmp_path)
    portrait = tmp_path / 'output/imagegen/nature-gallery'
    landscape = portrait / 'landscape'
    monkeypatch.setattr(worker, 'GALLERY', landscape)
    (portrait / 'images').mkdir(parents=True)
    source = portrait / 'images/sea_coast-02.png'
    source.write_bytes(b'original-painting')
    original = {'themes': [{'id': 'sea_coast', 'title': 'Sea', 'description': 'Coastal light',
        'images': [{'id': 'sea_coast-02', 'path': 'images/sea_coast-02.png', 'status': 'ready'}]}]}
    saved = {'sea_coast-02': {'favourite': True, 'notes': 'Keep this'}}
    worker.atomic_json(portrait / 'manifest.json', original)
    worker.atomic_json(portrait / 'state.json', saved)
    before = {name: (portrait / name).read_bytes() for name in ('manifest.json', 'state.json')}
    worker.initialize_landscape()
    result = worker.read_json(landscape / 'manifest.json')
    assert result['orientation'] == 'landscape'
    assert result['size'] == '1536x1024'
    assert len(result['themes'][0]['images']) == 2
    assert all(i['parent_image_id'] == 'sea_coast-02' for i in result['themes'][0]['images'])
    assert all(i['references'] == ['references/sea_coast-02.png'] for i in result['themes'][0]['images'])
    assert (landscape / 'references/sea_coast-02.png').read_bytes() == source.read_bytes()
    assert worker.read_json(landscape / 'portrait-favourites-snapshot.json') == saved
    assert all((portrait / name).read_bytes() == content for name, content in before.items())
    worker.initialize_landscape()  # Idempotent: no resets of later selections or generation state.
    assert worker.read_json(landscape / 'manifest.json') == result


def test_landscape_generation_uses_selected_reference_and_size(gallery, monkeypatch):
    from PIL import Image
    worker.mutate_manifest(lambda m: m.update(orientation='landscape', size='1536x1024'))
    worker.mutate_manifest(lambda m: worker.find_image(m, 'sea_coast-01').update(references=['references/favourite.png']))
    monkeypatch.setattr(worker, 'key_environment', lambda: {'OPENAI_API_KEY': 'test-secret'})
    commands = []
    def generated(command, **kwargs):
        commands.append(command)
        Image.new('RGB', (1536, 1024)).save(command[command.index('--out') + 1])
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(worker.subprocess, 'run', generated)
    assert worker.generate('sea_coast-01')
    command = commands[0]
    assert command[command.index('--size') + 1] == '1536x1024'
    assert command[command.index('--image') + 1] == str(gallery / 'references/favourite.png')
    assert worker.find_image(worker.read_json(gallery / 'manifest.json'), 'sea_coast-01')['status'] == 'ready'
