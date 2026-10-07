"""Run the backend locally against the small Campbell dev corpus.

Usage: runtime/venv-syntax/Scripts/python tools/serve_dev.py [--port 8795]

Points backend.server.DB at runtime/dev/corpus.sqlite (built by
scripts/dev_corpus_campbell.py) and the Morpheus cache at
runtime/dev/machine_morphology.sqlite. No Jev key is loaded; reranking stays
unavailable unless the environment already provides one.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', type=int, default=8795)
parser.add_argument('--corpus', type=Path, default=ROOT / 'runtime/dev/corpus.sqlite')
parser.add_argument('--machine-state', type=Path, default=ROOT / 'runtime/dev/machine_morphology.sqlite')
args = parser.parse_args()

os.environ.setdefault('MELOS_MACHINE_STATE', str(args.machine_state))
os.environ.setdefault('MELOS_CLASSIFIER_STATE', str(ROOT / 'runtime/dev/classifier.sqlite'))
os.environ.setdefault('MELOS_SYNTAX_MODEL_PATH', str(ROOT / 'runtime/models/odycy/pipeline'))

import backend.server as server  # noqa: E402

server.DB = args.corpus
import uvicorn  # noqa: E402

uvicorn.run(server.app, host='127.0.0.1', port=args.port, log_level='warning')
