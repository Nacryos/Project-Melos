# Project Melos

A source-backed research reader and lexicon for Ancient Greek lyric and its
literary traditions, using the original Melos painting, mosaic and dither design.
The frontend is plain HTML/CSS/JavaScript; the corpus API is Python/FastAPI.

## Research reader

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.server:app --host 127.0.0.1 --port 8791
```

Open http://127.0.0.1:8791. This requires locally provisioned, independently
accepted corpus/index files; a fresh code clone does not contain the datasets.
The full reader is served at `/`, and the original design/search page at
`/legacy`. Both use the real API, not the sample lexicon.

For Jev, configure `TYPESAFE_API_KEY` in a private `.env` and add
`--env-file .env` to the server command. Use `.env.example` for the non-secret
configuration names; never place a provider key in frontend settings.

Read [reader and source documentation](docs/reader.md),
[coverage and gaps](docs/coverage.md), and
[Vercel deployment preparation](docs/deployment.md).

The public repository contains application code, collectors, tests and design
assets. Downloaded source collections, derived corpora, extraction reports,
embeddings, model weights, credentials and generated indexes stay local.
Source rights and attribution remain record-specific; this repository does
not grant blanket redistribution rights over the collected texts.

## Original frontend and asset tools

```
python tools/serve.py          # static dev server, caching off; http://127.0.0.1:8790
python tools/build_images.py   # after adding/changing a painting in assets/source/
```

## Images
Originals live in `assets/source/` (not referenced by the page). `tools/build_images.py` writes AVIF + WebP
at 480/960/1600/2400 px (never upscaled) and a 160 px WebP thumbnail into `assets/paintings/`, with a content
hash in each filename, and regenerates `js/images.js`. The page shows a 480 px preview first (the dither hides
the softness), then swaps in the size the screen needs, then fetches the other paintings one at a time.

Because filenames change whenever content changes, serve `assets/paintings/*` with
`Cache-Control: public, max-age=31536000, immutable`.

- `js/dither.js`: WebGL ordered (Bayer 2/4/8) dithering, colour boost, palettes, reveal lens, and a Bayer-threshold dissolve between paintings.
- `js/app.js`: hero, dither controls (saved in localStorage; "Copy settings" gives JSON to hard-code as `DEFAULTS`), and the original search entry point connected to the corpus API.
- `data/lexicon.json`: historical **sample entries only**, retained with the original design history; not used as research evidence.

Keys: `D` toggles dither, `←` / `→` change painting.

The static design server on port 8790 does not provide the corpus API. Use the
research service on port 8791 for local integrated search, or configure a
separate API origin for a static deployment. Hashed painting assets receive
immutable caching; original source paintings and depth maps are not served.
