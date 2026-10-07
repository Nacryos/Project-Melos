"""Local gallery generation worker. Calls the installed imagegen CLI, never exposes keys.

Initial batch: --initialize then --initial (15 images, bounded concurrency).
Explicit gallery retry: --job output/imagegen/nature-gallery/jobs/<uuid>.json.
Each retry appends ONE new painting; no original is replaced.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
GALLERY = ROOT / 'output/imagegen/nature-gallery'
MODEL = 'gpt-image-2.5-sunburst'
THEMES = {'sea_coast', 'garden_grove', 'meadow_pasture', 'mountain_woodland', 'river_spring'}
CLI = Path('C:/Users/alvin/.codex/skills/.system/imagegen/scripts/image_gen.py')
BATCH_STOP = threading.Event()


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


@contextmanager
def manifest_lock():
    lock = GALLERY / '.manifest.lock'
    deadline = time.monotonic() + 20
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError('Manifest is locked; another update may still be running.')
            time.sleep(.05)
    try:
        yield
    finally:
        os.close(fd)
        lock.unlink()


def mutate_manifest(fn):
    with manifest_lock():
        path = GALLERY / 'manifest.json'
        value = read_json(path)
        result = fn(value)
        value['updated_at'] = now()
        atomic_json(path, value)
        return result


def key_environment():
    env = dict(os.environ)
    # Explicit gallery credential takes precedence without changing any global key.
    from dotenv import dotenv_values
    gallery_key = dotenv_values(ROOT / 'secrets/nature-gallery.env', encoding='utf-8-sig').get('OPENAI_API_KEY')
    if gallery_key:
        env['OPENAI_API_KEY'] = gallery_key
    if not env.get('OPENAI_API_KEY') and sys.platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
                env['OPENAI_API_KEY'] = winreg.QueryValueEx(key, 'OPENAI_API_KEY')[0]
        except OSError:
            pass
    if not env.get('OPENAI_API_KEY'):
        for path in (ROOT / '.env.local', ROOT / '.env', Path('C:/Users/alvin/.env')):
            value = dotenv_values(path, encoding='utf-8-sig').get('OPENAI_API_KEY')
            if value:
                env['OPENAI_API_KEY'] = value
                break
    if not env.get('OPENAI_API_KEY'):
        raise RuntimeError('OPENAI_API_KEY is not configured on this computer.')
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def initialize():
    GALLERY.mkdir(parents=True, exist_ok=True)
    path = GALLERY / 'manifest.json'
    with manifest_lock():
        if path.exists():
            return
        direction = read_json(GALLERY / 'art-direction.json')
        refs = ['references/alma-tadema.jpg', 'references/terrace-watercolour.png']
        for ref in refs:
            if not (GALLERY / ref).is_file():
                raise ValueError('Missing reference image: ' + ref)
        themes = []
        for theme in direction['themes']:
            if theme['id'] not in THEMES or len(theme['variants']) != 3:
                raise ValueError('Expected five themes, each with three variants.')
            themes.append({k: theme[k] for k in ('id', 'title', 'description')} | {
                'images': [dict(id=v['id'], path='images/' + v['id'] + '.png',
                                prompt=v['prompt'], status='pending') for v in theme['variants']]})
        if {t['id'] for t in themes} != THEMES or len(themes) != 5:
            raise ValueError('Theme manifest mismatch.')
        atomic_json(path, {'version': 1, 'created_at': now(), 'updated_at': now(),
            'image_model': MODEL, 'direction_model': direction['direction_model'],
            'direction_reasoning_effort': direction['reasoning_effort'],
            'size': '1024x1536', 'quality': 'high', 'references': refs,
            'reference_hashes': {r: hashlib.sha256((GALLERY / r).read_bytes()).hexdigest() for r in refs},
            'themes': themes})


def find_image(manifest, image_id):
    for theme in manifest['themes']:
        for image in theme['images']:
            if image['id'] == image_id:
                return image
    raise ValueError('Unknown image ID.')


def initialize_landscape():
    """Snapshot favourite portraits and extend them without modifying the originals."""
    source_dir = ROOT / 'output/imagegen/nature-gallery'
    GALLERY.mkdir(parents=True, exist_ok=True)
    with manifest_lock():
        if (GALLERY / 'manifest.json').exists():
            return
        original = read_json(source_dir / 'manifest.json')
        state = read_json(source_dir / 'state.json')
        selected = []
        for theme in original['themes']:
            favourites = [i for i in theme['images'] if state.get(i['id'], {}).get('favourite')]
            if len(favourites) != 1 or favourites[0]['status'] != 'ready':
                raise ValueError('Expected exactly one ready favourite for ' + theme['id'])
            selected.append((theme, favourites[0]))
        (GALLERY / 'references').mkdir(exist_ok=True)
        themes, hashes = [], {}
        for theme, favourite in selected:
            ref = 'references/' + favourite['id'] + '.png'
            source = (source_dir / favourite['path']).resolve()
            if source.parent != (source_dir / 'images').resolve():
                raise ValueError('Favourite must be in the portrait images directory.')
            shutil.copy2(source, GALLERY / ref)
            hashes[ref] = hashlib.sha256(source.read_bytes()).hexdigest()
            prompt = (
                'Use case: precise-object-edit\n'
                'Input image 1: the selected finished portrait painting, the EDIT TARGET, not merely a style reference.\n'
                'Primary request: keep this painting identical as closely as possible, but extend it to the left and right '
                'so it becomes a wider LANDSCAPE painting, aspect ratio 3:2. Seamlessly outpaint the existing scene.\n'
                'Preserve the entire original vertical view, its recognisable features, their relative positions and proportions, '
                'the horizon height, perspective, colours, lighting, shadows, delicate watercolour paper texture, brushwork, '
                'and classical romantic atmosphere. Uniformly scale the original to fit the output height; add natural continuation '
                'on both sides. Do not crop away the top or bottom, stretch the painting, mirror or duplicate its features, '
                'or redesign the composition. Only the newly extended side areas should introduce new scenery.\n'
                'Continue the same sky, terrain, vegetation and water already present, as appropriate at each edge. '
                'Keep the extension restrained and spacious, suitable as a poem-header background. '
                'No people, text, lettering, frames, watermarks, new narrative objects or unrelated architectural features.\n'
                'Theme for continuity: ' + theme['title'] + '. '
                'The attached painting is authoritative; retain its specific scene rather than inventing a new interpretation.'
            )
            images = []
            for number in (1, 2):
                image_id = theme['id'] + '-landscape-' + str(number).zfill(2)
                images.append(dict(id=image_id, path='images/' + image_id + '.png',
                    prompt=prompt, references=[ref], status='pending', parent_image_id=favourite['id']))
            themes.append({k: theme[k] for k in ('id', 'title', 'description')} | {'images': images})
        atomic_json(GALLERY / 'portrait-favourites-snapshot.json', state)
        atomic_json(GALLERY / 'manifest.json', dict(version=1, created_at=now(), updated_at=now(),
            title='Landscape studies', orientation='landscape', image_model=MODEL,
            size='1536x1024', quality='high', references=[], reference_hashes=hashes, themes=themes))


def claim_image(manifest, image_id):
    image = find_image(manifest, image_id)
    if image['status'] != 'pending':
        raise ValueError('Only pending images can be generated; retries need a new ID.')
    image.update(status='generating', started_at=now(), attempt_id=uuid.uuid4().hex[:12])
    image.pop('error', None)
    image.pop('error_code', None)
    return dict(image)


def generate(image_id):
    if BATCH_STOP.is_set():
        return False
    image = mutate_manifest(lambda m: claim_image(m, image_id))
    directory = GALLERY / 'prompts'
    directory.mkdir(exist_ok=True)
    prompt_path = directory / (image_id + '.txt')
    prompt_path.write_text(image['prompt'], encoding='utf-8')
    output = GALLERY / image['path']
    output.parent.mkdir(exist_ok=True)
    log_dir = GALLERY / 'logs'
    log_dir.mkdir(exist_ok=True)
    manifest = read_json(GALLERY / 'manifest.json')
    command = [sys.executable, str(CLI), 'edit', '--model', MODEL,
               '--prompt-file', str(prompt_path), '--no-augment', '--n', '1',
               '--size', manifest.get('size', '1024x1536'), '--quality', 'high', '--output-format', 'png',
               '--out', str(output)]
    for ref in image.get('references', manifest['references']):
        command += ['--image', str(GALLERY / ref)]
    print(f'Generating {image_id}', flush=True)
    try:
        env = key_environment()
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=1200)
        # Never persist keys even if an upstream exception unexpectedly echoes one.
        output_log = (result.stdout + '\n' + result.stderr).replace(env['OPENAI_API_KEY'], '[redacted]')
        (log_dir / (image_id + '-' + image['attempt_id'] + '.log')).write_text(output_log, encoding='utf-8')
        if 'credit_balance_exhausted' in output_log or 'insufficient_quota' in output_log:
            BATCH_STOP.set()
            mutate_manifest(lambda m: m.update(generation_blocker='api_credits_required'))
            raise RuntimeError('API credits needed. Add credits to the OpenAI account, then try again.')
        if result.returncode or not output.exists():
            raise RuntimeError('Image API did not produce an image. See the local generation log.')
        from PIL import Image
        with Image.open(output) as painting:
            width, height = painting.size
            painting.verify()
        landscape = manifest.get('orientation') == 'landscape'
        if (landscape and width <= height) or (not landscape and height <= width):
            raise RuntimeError('Generated image has the wrong orientation.')
        receipt = dict(status='ready', completed_at=now(), width=width, height=height,
                       sha256=hashlib.sha256(output.read_bytes()).hexdigest(), model=MODEL)
        def complete(m):
            find_image(m, image_id).update(receipt)
            m.pop('generation_blocker', None)
        mutate_manifest(complete)
        print(f'Ready {image_id}', flush=True)
        return True
    except Exception as exc:
        error = str(exc) if isinstance(exc, RuntimeError) else 'Generation failed; inspect local logs.'
        mutate_manifest(lambda m: find_image(m, image_id).update(status='failed', error=error, completed_at=now()))
        print(f'Failed {image_id}: {error}', flush=True)
        return False


def validate_job(path):
    path = path.resolve()
    jobs = (GALLERY / 'jobs').resolve()
    if path.parent != jobs or path.suffix != '.json' or not path.is_file():
        raise ValueError('Job must be an existing JSON file inside the gallery jobs directory.')
    if path.stat().st_size > 20000:
        raise ValueError('Job is too large.')
    job = read_json(path)
    if job.get('theme_id') not in THEMES:
        raise ValueError('Unknown theme.')
    if not isinstance(job.get('notes', ''), str) or len(job.get('notes', '')) > 2000:
        raise ValueError('Notes must be at most 2000 characters.')
    return job


def retry_job(path):
    # A persistent cross-process guard also covers gallery restarts.
    lock = GALLERY / '.manual-generation.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError('Another manual generation is active. Wait for it to finish.') from exc
    try:
        os.write(fd, json.dumps({'pid': os.getpid(), 'started_at': now()}).encode())
        return _retry_job(path)
    finally:
        os.close(fd)
        lock.unlink()


def _retry_job(path):
    job = validate_job(path)
    # Claim this job exactly once, including if a server accidentally starts it twice.
    claim = path.with_suffix('.claimed')
    with claim.open('x', encoding='utf-8') as stream:
        stream.write(now())
    image_id = job['theme_id'] + '-retry-' + uuid.uuid4().hex[:12]
    def append(manifest):
        theme = next(t for t in manifest['themes'] if t['id'] == job['theme_id'])
        source = next((i for i in theme['images'] if i['id'] == job.get('image_id')), None)
        if job.get('image_id') and source is None:
            raise ValueError('Reference variant is not in the requested theme.')
        source = source or theme['images'][0]
        prompt = source['prompt'] + '\n\nRevision notes from the art director:\n' + job.get('notes', '')
        references = source.get('references', manifest['references'])
        if source.get('status') == 'ready':
            target = (GALLERY / source['path']).resolve()
            if target.parent != (GALLERY / 'images').resolve() or not target.is_file():
                raise ValueError('Selected painting must exist in this collection.')
            references = [source['path']]
            # Edit the actual chosen version, not its old portrait/style references.
            # Do not retain old outpainting instructions that conflict with this edit.
            prompt = (
                'Use case: precise-object-edit\n'
                'Input image 1: the selected finished painting, the EDIT TARGET.\n'
                'Make only the changes requested below. Preserve the existing aspect ratio, framing, '
                'watercolour medium, paper texture, palette, illumination and all unmentioned details. '
                'Do not redesign the whole scene or add text, borders or watermarks.\n\n'
                'Requested changes:\n' + job.get('notes', '')
            )
        theme['images'].append(dict(id=image_id, path='images/' + image_id + '.png', prompt=prompt,
                                    references=references,
                                    status='pending', job_id=job.get('job_id'), parent_image_id=source['id']))
    mutate_manifest(append)
    success = generate(image_id)
    atomic_json(path.with_name(path.stem + '.result.json'), {
        'job_id': job.get('job_id'), 'image_id': image_id, 'status': 'ready' if success else 'failed', 'completed_at': now()})
    return success


def main():
    global GALLERY
    parser = argparse.ArgumentParser()
    parser.add_argument('--collection', choices=('portrait', 'landscape'), default='portrait')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--initialize', action='store_true')
    action.add_argument('--initial', action='store_true')
    action.add_argument('--retry-image', help='Explicitly retry one failed initial image.')
    action.add_argument('--resume-initial', action='store_true', help='Explicitly retry failed initial images after resolving the cause.')
    action.add_argument('--job', type=Path)
    args = parser.parse_args()
    if args.collection == 'landscape':
        GALLERY = ROOT / 'output/imagegen/nature-gallery/landscape'
    if args.initialize:
        (initialize_landscape if args.collection == 'landscape' else initialize)()
    elif args.job:
        if not retry_job(args.job):
            raise SystemExit(1)
    elif args.retry_image:
        def retry_one(m):
            image = find_image(m, args.retry_image)
            if image['status'] != 'failed' or image.get('job_id'):
                raise ValueError('Only a failed initial image can be retried by this command.')
            image.setdefault('attempts', []).append({key: image.get(key) for key in
                ('attempt_id', 'status', 'error', 'started_at', 'completed_at')})
            image['status'] = 'pending'
        mutate_manifest(retry_one)
        if not generate(args.retry_image):
            raise SystemExit(1)
    else:
        if args.resume_initial:
            def resume(m):
                for theme in m['themes']:
                    for image in theme['images']:
                        if image['status'] == 'failed' and not image.get('job_id'):
                            image.setdefault('attempts', []).append({key: image.get(key) for key in
                                ('attempt_id', 'status', 'error', 'started_at', 'completed_at')})
                            image['status'] = 'pending'
                m.pop('generation_blocker', None)
            mutate_manifest(resume)
        manifest = read_json(GALLERY / 'manifest.json')
        pending = [i['id'] for t in manifest['themes'] for i in t['images']
                   if i['status'] == 'pending' and not i.get('job_id')]
        key_environment()  # Preflight before marking any images in flight.
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(generate, pending))
        if not all(results):
            raise SystemExit(1)


if __name__ == '__main__':
    main()
