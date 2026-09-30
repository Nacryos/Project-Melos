# Melos

Front-end prototype for a lexicon of archaic Greek lyric. Plain HTML/CSS/JS, no build step.

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
- `js/app.js`: hero, dither controls (saved in localStorage; "Copy settings" gives JSON to hard-code as `DEFAULTS`), and lexicon search (Greek accent-insensitive, Beta Code, English).
- `data/lexicon.json`: **sample entries only**. Swap for the corpus backend (same shape: `lemma, pos, gloss, note, attestations[{poet, cite, text, tr}]`).

Keys: `D` toggles dither, `←` / `→` change painting.
