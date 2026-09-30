# Melos

Front-end prototype for a lexicon of archaic Greek lyric. Plain HTML/CSS/JS, no build step.

```
python -m http.server 8790
# open http://127.0.0.1:8790
```

- `js/dither.js`: WebGL ordered (Bayer 2/4/8) dithering, colour boost, palettes, reveal lens, and a Bayer-threshold dissolve between paintings.
- `js/app.js`: hero, dither controls (saved in localStorage; "Copy settings" gives JSON to hard-code as `DEFAULTS`), and lexicon search (Greek accent-insensitive, Beta Code, English).
- `data/lexicon.json`: **sample entries only**. Swap for the corpus backend (same shape: `lemma, pos, gloss, note, attestations[{poet, cite, text, tr}]`).

Keys: `D` toggles dither, `←` / `→` change painting.
