"""Human-style check of the live reader with real clicks (release R).

Opens Sappho and Alcaeus fragments in headless Chromium at 1440x900 (mouse) and 390x844 (touch), clicks
words at their on-screen position (a real pointer event, so the reader's own hit-testing runs), reads what
the word panel shows (headword, gloss, printed form, parse, other parses, probability), selects a short
phrase with "Select phrase" and records the interlinear breakdown. Every word is clicked in the --full
passages. Results and screenshots go to --out; nothing is sent anywhere but the given origin, with a
generic project User-Agent.

    python scripts/human_check_reader.py --origin https://greeklyric.com --out output/human-check-r
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SAPPHO = ["1", "2", "5", "16", "31", "34", "44", "94", "96", "102"]
ALCAEUS = ["6", "38a", "42", "45", "129", "130b", "326", "346", "347", "350"]
FULL = ["campbell-glp:sappho:31", "campbell-glp:sappho:2", "campbell-glp:alcaeus:346", "campbell-glp:alcaeus:42"]
UA = "Melos/1.0 (+https://greeklyric.com)"
VIEWPORTS = {"desktop": {"viewport": {"width": 1440, "height": 900}},
             "phone": {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True,
                       "device_scale_factor": 2}}

READ_PANEL = """() => {
  const q = s => [...document.querySelectorAll(s)].filter(e => e.offsetParent !== null || e.getClientRects().length);
  const host = q('.word-headline-host').pop();
  if (!host) return null;
  const text = s => { const e = host.querySelector(s); return e ? e.innerText.trim() : ''; };
  let box = host; for (let k = 0; k < 4 && box.parentElement; k++) box = box.parentElement;
  return { lemma: text('.word-headline-lemma'), gloss: text('.word-headline-gloss'), form: text('.word-headline-form'),
           parse: text('.word-headline-parse'), note: text('.word-headline-note'),
           panel: box.innerText.slice(0, 1600) };
}"""


def tap(page, locator, touch):
    locator.scroll_into_view_if_needed()
    time.sleep(0.15)
    box = locator.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    if touch:
        page.touchscreen.tap(x, y)
    else:
        page.mouse.click(x, y)


def read_word(page, word_text, timeout=30, still=2.5):
    """Wait until the panel shows the clicked word with a parse and its meaning looked up, and has then
    stayed unchanged for `still` seconds (the passage reading replaces the index's provisional one)."""
    end = time.time() + timeout
    value, since = None, None
    while time.time() < end:
        current = page.evaluate(READ_PANEL)
        ready = current and word_text.split("’")[0][:3] in (current.get("form") or "") + (current.get("lemma") or "") +             current.get("panel", "") and "Looking up" not in current.get("gloss", "") and current.get("parse")
        if ready and current == value:
            if since and time.time() - since >= still:
                return current
        else:
            since = time.time() if ready else None
        value = current
        time.sleep(0.3)
    return value


def phrase(page, words, start, length, touch):
    out = {"start": start, "words": [words.nth(i).inner_text() for i in range(start, min(start + length, words.count()))]}
    try:
        page.get_by_role("button", name="Select phrase").first.click(timeout=8000)
        tap(page, words.nth(start), touch)
        time.sleep(0.5)
        tap(page, words.nth(min(start + length - 1, words.count() - 1)), touch)
        time.sleep(0.5)
        analyse = page.get_by_role("button", name="Analyze selection")
        if analyse.count():
            analyse.first.click(timeout=8000)
        page.wait_for_selector(".interlinear-content", timeout=45000)
        time.sleep(1.5)
        out["interlinear"] = page.locator(".interlinear-content").first.inner_text()[:1500]
    except Exception as exc:  # noqa: BLE001 - recorded as a finding
        out["error"] = str(exc)[:300]
    return out


def run(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    passages = [f"campbell-glp:sappho:{n}" for n in SAPPHO] + [f"campbell-glp:alcaeus:{n}" for n in ALCAEUS]
    if args.only:
        passages = [p for p in passages if p in args.only]
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name, options in VIEWPORTS.items():
            if args.viewport and name not in args.viewport:
                continue
            touch = bool(options.get("has_touch"))
            for pid in passages:
                ctx = browser.new_context(user_agent=UA, **options)
                page = ctx.new_page()
                record = {"passage": pid, "viewport": name, "clicks": [], "phrase": None}
                try:
                    page.goto(f"{args.origin}/?id={pid}", wait_until="domcontentloaded", timeout=90000)
                    page.wait_for_selector("button.word", timeout=90000)
                    time.sleep(3)
                    words = page.locator("button.word")
                    n = words.count()
                    full = pid in FULL and name == "desktop"
                    picks = list(range(n)) if full else sorted({0, n // 3, (2 * n) // 3, n - 1})
                    for i in picks:
                        text = words.nth(i).inner_text()
                        try:
                            tap(page, words.nth(i), touch)
                            value = read_word(page, text)
                        except Exception as exc:  # noqa: BLE001
                            value = {"error": str(exc)[:200]}
                        record["clicks"].append({"i": i, "word": text, "start": words.nth(i).get_attribute("data-source-start"),
                                                 **(value or {"error": "no panel"})})
                    page.screenshot(path=str(out / f"{pid.replace(':', '_')}-{name}.png"), full_page=False)
                    record["phrase"] = phrase(page, words, max(0, n // 2 - 1), 3, touch)
                    page.screenshot(path=str(out / f"{pid.replace(':', '_')}-{name}-phrase.png"), full_page=False)
                    record["words"] = n
                except Exception as exc:  # noqa: BLE001
                    record["error"] = str(exc)[:300]
                results.append(record)
                print(pid, name, len(record["clicks"]), "clicks", record.get("error", ""), flush=True)
                ctx.close()
        browser.close()
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin", default="https://greeklyric.com")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--viewport", nargs="*")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
