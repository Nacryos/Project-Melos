# TypeGreek rules (as implemented by js/typegreek.js)

Sources, read 2026-10-09 with the generic User-Agent `Melos/1.0 (+https://greeklyric.com)`:
- https://typegreek.com/ (the converter page: a textarea whose keypress runs `convertCharToggle` while
  "Convert to Greek" is ticked, and whose keyup runs `convertStr`);
- https://typegreek.com/alphabet.key/ (letter chart, diacritic chart, "TypeGreek vs. Standard Beta Code");
- https://typegreek.com/overview/ (beta code and the Iliad 1.1–5 example);
- https://typegreek.com/typegreek.js (the site's own converter, by Randy Hoyt): the authority for every
  detail below. It was run, unmodified, in a sandbox as the reference for the tests; it is not copied
  into Melos.

## 1. Keys (with Greek on)

| Key | Greek | Key | Greek | Key | Greek | Key | Greek |
|---|---|---|---|---|---|---|---|
| a | α | i | ι | r | ρ | x | χ |
| b | β | k | κ | s | σ (final ς by rule 4) | y | ψ |
| g | γ | l | λ | t | τ | w | ω |
| d | δ | m | μ | u | υ | j | ς (then rule 4: j and s are interchangeable) |
| e | ε | n | ν | f | φ | v | ϝ (digamma) |
| z | ζ | c | ξ | o | ο | q | θ |
| h | η | p | π | | | | |

Capitals: Shift + the letter (A → Α … W → Ω, C → Ξ, Q → Θ, J → Σ, S → Σ, V → Ϝ). The beta-code asterisk is
**not** used: `*` stays `*`, and diacritics are typed **after** a capital, as after a small letter.

| Key | Inserts | Meaning |
|---|---|---|
| `/` | ´ (U+00B4) | acute |
| `\` or `&` (or a typed `` ` ``) | `` ` `` (U+0060) | grave |
| `=` | ῀ (U+1FC0) | circumflex |
| `)` | ᾿ (U+1FBF) | smooth breathing |
| `(` | ῾ (U+1FFE) | rough breathing |
| `\|` or `!` | ͺ (U+037A) | iota subscript |
| `+` | ¨ (U+00A8) | diaeresis |
| `;` and `:` | · (U+00B7) | ano teleia (Greek semicolon / colon) |
| `?` | ; (U+003B) | Greek question mark (U+037E is canonically U+003B) |
| `@` | ̣ (U+0323) | dot below (uncertain letter) |

Every other key (digits, space, `,` `.` `'` `"` `-` `[` `]` `*` …) is typed as itself. With Ctrl or Cmd held
nothing is converted. Macron and breve are not supported by TypeGreek, so not here either.

## 2. After every keystroke (Greek on or off)

1. **Break apart.** Each precomposed vowel or rho TypeGreek can build is split back into letter + spacing
   marks (breathing, accent, then iota subscript or diaeresis); ς becomes σ.
2. **Combine.** Reading left to right, each letter of `ΑαΗηΩωΕεΙιΟοΡρΥυ` takes the marks that follow it, one
   by one, while each is allowed (below), in **any order**; the letter and its marks become the precomposed
   Unicode character. A mark that is not allowed stays in the text as typed (`k/` → κ´, `a//` → ά´, `e=` → ε῀,
   `r)` → ρ᾿, `i)+` → ἰ¨).
3. **Final sigma.** A lowercase σ becomes ς when the next character is a return, `,` `;` `.` space `:` `·` or
   `;` — or a dot below followed by one of those (or by the end of the text). σ at the very end of the box
   stays σ until the next character is typed (TypeGreek behaves the same).

**When a mark is allowed** (w = the letter with the marks it already has; "next" = the character after the mark):

| Mark | Small letter | Capital letter |
|---|---|---|
| acute / grave | any vowel without an accent | any vowel without an accent; Ι Υ only without diaeresis; Α Η Ω not when they have an iota subscript and no breathing |
| circumflex | α η ω ι υ without an accent | Α Η Ω only with a breathing (already, or as the next character, or iota subscript then breathing next); Ι with a breathing; Υ with a rough breathing; never with a diaeresis |
| rough breathing | any vowel or ρ without a breathing or diaeresis | the same (Ρ included) |
| smooth breathing | any vowel except ρ, without a breathing or diaeresis | the same, except Υ and Ρ |
| iota subscript | α η ω without one | Α Η Ω without one, either without an accent or with a breathing (already or next) |
| diaeresis | ι υ without a breathing or diaeresis | Ι Υ without a breathing, diaeresis or accent |

So typing order never matters as long as the result is a real character: `a)/|`, `a/|)`, `a|)/` all give ᾄ;
`A=)|` and `A|=)` give ᾎ; `i+/` and `i/+` give ΐ.

## 3. What Melos adds (TypeGreek has none of these)

| Addition | Behaviour |
|---|---|
| Scope of the pass | Run on the edited word (between the whitespace around the edit) instead of the whole box. The result for that word is identical (the pass never joins across whitespace; final sigma reads the next character); pasted Greek and English typed with Greek off elsewhere stay untouched. |
| Mobile keyboards | Android Gboard and other keyboards that compose a word send it on commit (`compositionend`), autocorrect sends `insertReplacementText`, paste `insertFromPaste`: all reach the same edit path (the text inserted since the last edit is found by comparing the old and new value), so a committed Latin word converts as if typed key by key. Nothing is changed while a word is still being composed. `autocapitalize=off autocorrect=off autocomplete=off spellcheck=false` are set. |
| Paste | Pasted text with no Greek letters converts when Greek is on; pasted text that contains Greek letters is left alone (only NFC-normalised). |
| Toggle | Greek ⇄ English button (large tap target on the composer page) and Ctrl+` ; the choice is remembered per viewer in `localStorage` (every access wrapped in try/catch). |
| Output | NFC: ά is U+03AC, ΐ U+0390 (TypeGreek's own output is already NFC). |
| Caret | Kept where TypeGreek keeps it: after the character a mark joined; unchanged when the edit is elsewhere. |

## 4. Tests

- `tests/typegreek.test.mjs` (node): 270 keystroke sequences (`tests/fixtures/typegreek-cases.json`: every
  letter, every chart diacritic, mark combinations in several orders, capitals, marks that do not fit, final
  sigma before each terminator, punctuation keys, the Overview's Iliad lines and Sappho lines); each expected
  value is what typegreek.com's script produced for those keys. All 270 match, typed at once and key by key.
- Development only (not committed, as the reference script is not ours): 120,000 random key sequences
  (letters, every mark key, punctuation, space, return, Backspace, caret moves, Greek on and off) typed into
  both typegreek.com's script and js/typegreek.js: identical text and caret in all of them.
