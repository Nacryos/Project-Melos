### A. Hypotactic Iliad, Books 13-24 (held out from calibration)

8102 lines; 167 lines have a synizesis merger the metre-free scanner leaves as two units.

| Setting | Units scored | Decided (p = 0/1 or ≤0.1/≥0.9) | Accuracy on decided | Ambiguous | Brier |
|---|---|---|---|---|---|
| rules as written, core only | 119,412 | 73.6 % | 99.62 % | 26.4 % | 0.0669 |
| rules as written + lexicon | 119,412 | 90.0 % | 99.29 % | 10.1 % | 0.0293 |
| parameters set to Homer's measured shares, core only | 119,412 | 75.9 % | 99.59 % | 24.1 % | 0.061 |
| measured parameters + lexicon | 119,412 | 92.8 % | 99.25 % | 7.2 % | 0.0217 |

Synizesis: 167 mergers in the gold, 152 flagged SYN-CAND.

Speed (500 lines): {'speed_warm_lexicon': {'lines': 500, 'median_ms': 1.655, 'p95_ms': 2.121, 'max_ms': 3.15}, 'speed_cold_lexicon_cache_cleared_per_line': {'lines': 500, 'median_ms': 2.069, 'p95_ms': 2.936, 'max_ms': 3.869}, 'speed_without_lexicon': {'lines': 500, 'median_ms': 1.161, 'p95_ms': 1.413, 'max_ms': 2.168}} 

Calibration (rules as written + lexicon):

| p band | units | observed long |
|---|---|---|
| 0.0-0.1 | 47,002 | 0.006 |
| 0.1-0.2 | 8,092 | 0.035 |
| 0.2-0.3 | 84 | 0.083 |
| 0.3-0.4 | 410 | 0.278 |
| 0.4-0.5 | 126 | 0.27 |
| 0.5-0.6 | 9,924 | 0.442 |
| 0.6-0.7 | 27 | 0.333 |
| 0.7-0.8 | 191 | 0.89 |
| 0.8-0.9 | 183 | 0.743 |
| 0.9-1.0 | 53,373 | 0.995 |

Calibration (measured parameters + lexicon):

| p band | units | observed long |
|---|---|---|
| 0.0-0.1 | 55,094 | 0.01 |
| 0.1-0.2 | 84 | 0.083 |
| 0.2-0.3 | 3,470 | 0.246 |
| 0.3-0.4 | 125 | 0.264 |
| 0.5-0.6 | 3,664 | 0.173 |
| 0.6-0.7 | 45 | 0.289 |
| 0.7-0.8 | 183 | 0.743 |
| 0.8-0.9 | 1,045 | 0.844 |
| 0.9-1.0 | 55,702 | 0.995 |

### B. Owner's hexameter scansions, held-out chunks (rules as written)

| Work | Lines | Units | Core: decided / accuracy / ambiguous / Brier | + lexicon: decided / accuracy / ambiguous / Brier |
|---|---|---|---|---|
| iliad | 160 | 2,320 | 73.8 % / 99.65 % / 26.2 % / 0.0665 | 90.6 % / 99.52 % / 9.4 % / 0.0256 |
| odyssey | 160 | 2,319 | 74.4 % / 99.65 % / 25.6 % / 0.0656 | 92.1 % / 99.48 % / 7.9 % / 0.024 |
| homeric_hymns | 160 | 2,270 | 73.4 % / 99.88 % / 26.7 % / 0.0659 | 91.2 % / 99.28 % / 8.8 % / 0.0259 |
| theogony | 160 | 2,210 | 74.8 % / 99.94 % / 25.2 % / 0.063 | 92.0 % / 99.36 % / 8.0 % / 0.0228 |
| works_and_days | 160 | 2,209 | 76.6 % / 99.76 % / 23.4 % / 0.0594 | 93.0 % / 99.42 % / 7.0 % / 0.0208 |
| shield | 160 | 2,247 | 72.9 % / 99.45 % / 27.1 % / 0.07 | 91.5 % / 98.35 % / 8.5 % / 0.0333 |
| argonautica | 160 | 2,312 | 72.2 % / 99.88 % / 27.9 % / 0.0683 | 91.3 % / 99.53 % / 8.7 % / 0.024 |
| quintus_posthomerica | 160 | 2,308 | 74.0 % / 99.94 % / 26.0 % / 0.0639 | 90.9 % / 99.52 % / 9.1 % / 0.0243 |
| nonnus_dionysiaca | 160 | 2,392 | 74.7 % / 100.00 % / 25.3 % / 0.0605 | 91.3 % / 99.36 % / 8.6 % / 0.0237 |
| ALL | 1440 | 20,587 | 74.1 % / 99.80 % / 25.9 % / 0.0648 | 91.5 % / 99.32 % / 8.5 % / 0.025 |

### B. Owner's hexameter scansions, held-out chunks (measured parameters)

| Work | Lines | Units | Core: decided / accuracy / ambiguous / Brier | + lexicon: decided / accuracy / ambiguous / Brier |
|---|---|---|---|---|
| iliad | 160 | 2,320 | 76.4 % / 99.66 % / 23.6 % / 0.0592 | 94.0 % / 99.54 % / 6.0 % / 0.0161 |
| odyssey | 160 | 2,319 | 76.0 % / 99.66 % / 24.0 % / 0.0612 | 94.6 % / 99.36 % / 5.4 % / 0.0185 |
| homeric_hymns | 160 | 2,270 | 75.9 % / 99.83 % / 24.1 % / 0.0576 | 94.3 % / 99.30 % / 5.7 % / 0.016 |
| theogony | 160 | 2,210 | 76.8 % / 99.82 % / 23.2 % / 0.0567 | 95.0 % / 99.29 % / 5.0 % / 0.0155 |
| works_and_days | 160 | 2,209 | 78.2 % / 99.71 % / 21.8 % / 0.0542 | 95.3 % / 99.43 % / 4.7 % / 0.0145 |
| shield | 160 | 2,247 | 75.4 % / 99.17 % / 24.6 % / 0.0647 | 94.8 % / 98.17 % / 5.2 % / 0.027 |
| argonautica | 160 | 2,312 | 74.2 % / 99.88 % / 25.8 % / 0.0609 | 94.2 % / 99.49 % / 5.8 % / 0.015 |
| quintus_posthomerica | 160 | 2,308 | 76.3 % / 99.77 % / 23.7 % / 0.0588 | 94.2 % / 99.40 % / 5.9 % / 0.0174 |
| nonnus_dionysiaca | 160 | 2,392 | 78.2 % / 99.95 % / 21.8 % / 0.0531 | 95.9 % / 99.35 % / 4.1 % / 0.0139 |
| ALL | 1440 | 20,587 | 76.4 % / 99.72 % / 23.6 % / 0.0585 | 94.7 % / 99.26 % / 5.3 % / 0.0171 |

### C. Hypotactic open corpus, held-out chunks, by metre class

| Class | Lexicon | Lines | Units | Decided | Accuracy on decided | Ambiguous | Brier |
|---|---|---|---|---|---|---|---|
| hexameter | none | 871 | 12,992 | 73.9 % | 99.78 % | 26.1 % | 0.0648 |
| hexameter | wiktionary | 871 | 12,992 | 86.0 % | 99.58 % | 14.0 % | 0.0353 |
| hexameter | full | 871 | 12,992 | 90.9 % | 99.34 % | 9.1 % | 0.0262 |
| pentameter | none | 617 | 7,373 | 74.5 % | 99.76 % | 25.5 % | 0.0645 |
| pentameter | wiktionary | 617 | 7,373 | 89.2 % | 99.51 % | 10.8 % | 0.0293 |
| pentameter | full | 617 | 7,373 | 93.5 % | 99.22 % | 6.5 % | 0.0218 |
| iambic_trochaic_anapaestic | none | 2348 | 25,184 | 78.8 % | 99.89 % | 21.2 % | 0.0553 |
| iambic_trochaic_anapaestic | wiktionary | 2348 | 25,184 | 88.8 % | 99.48 % | 11.2 % | 0.0317 |
| iambic_trochaic_anapaestic | full | 2348 | 25,184 | 93.4 % | 99.18 % | 6.6 % | 0.0231 |
| lyric_and_other | none | 1852 | 22,538 | 72.0 % | 99.91 % | 28.1 % | 0.0707 |
| lyric_and_other | wiktionary | 1852 | 22,538 | 84.8 % | 99.62 % | 15.2 % | 0.04 |
| lyric_and_other | full | 1852 | 22,538 | 92.5 % | 99.21 % | 7.5 % | 0.0245 |

### D. Metre layer on the same held-out lines

| Metre | Lexicon | Lines | Fit without overruling the scanner | Lines with every weight right | Unit accuracy after fit | Ambiguous before → after | Auto-detect top-1 |
|---|---|---|---|---|---|---|---|
| hexameter | none | 871 | 97.5 % | 96.6 % | 99.64 % | 26.1 % → 0.3 % | 99.3 % |
| pentameter | none | 617 | 99.4 % | 98.4 % | 99.66 % | 25.5 % → 0.2 % | 99.5 % |
| iambic_trimeter | none | 930 | 99.1 % | 60.3 % | 95.53 % | 20.7 % → 5.9 % | 99.4 % |
| trochaic_tetrameter | none | 59 | 94.9 % | 49.1 % | 95.69 % | 21.4 % → 5.8 % | 94.9 % |
| hexameter | full | 871 | 96.8 % | 96.9 % | 99.74 % | 9.1 % → 0.1 % | 99.5 % |
| pentameter | full | 617 | 99.4 % | 98.4 % | 99.66 % | 6.5 % → 0.1 % | 99.7 % |
| iambic_trimeter | full | 930 | 98.7 % | 82.0 % | 98.30 % | 6.8 % → 2.3 % | 99.4 % |
| trochaic_tetrameter | full | 59 | 94.9 % | 74.6 % | 98.23 % | 5.8 % → 1.8 % | 94.9 % |

### E. Norma (vowel lengths of α ι υ, independent of Hypotactic)

| Lexicon | Marked α ι υ | Decided | Accuracy on decided | Ambiguous |
|---|---|---|---|---|
| none | 4,374 | 546 | 98.72 % | 87.5 % |
| wiktionary | 4,374 | 2,868 | 97.91 % | 34.4 % |
| full | 4,374 | 3,593 | 96.47 % | 17.9 % |

By source (full lexicon):

| Source | Marked | Decided | Accuracy | Ambiguous |
|---|---|---|---|---|
| acharnenses | 48 | 40 | 97.50 % | 16.7 % |
| aristophanes | 3385 | 2745 | 96.68 % | 18.9 % |
| bacchylides | 360 | 322 | 95.03 % | 10.6 % |
| contracelsum | 74 | 47 | 93.62 % | 36.5 % |
| cratylus | 44 | 35 | 91.43 % | 20.4 % |
| cyclops | 39 | 36 | 97.22 % | 7.7 % |
| dionysiaca | 49 | 46 | 97.83 % | 6.1 % |
| dioscorides | 40 | 37 | 91.89 % | 7.5 % |
| enchiridion | 46 | 30 | 100.00 % | 34.8 % |
| oedipus | 39 | 38 | 94.74 % | 2.6 % |
| partheneion | 30 | 29 | 89.66 % | 3.3 % |
| plutarchus | 82 | 62 | 98.39 % | 24.4 % |
| quintus | 55 | 50 | 96.00 % | 9.1 % |
| supplices | 22 | 19 | 100.00 % | 13.6 % |
| thucydides | 61 | 57 | 100.00 % | 6.6 % |

Core, lyric_and_other, ambiguity by rule: {'NATURE/DICH-UNK': 4612, 'MCL-WORD': 562, 'CONS-VOW/DICH-UNK': 544, 'EPL-INIT': 245, 'MCL-INIT': 200, 'COR-EXT': 112, 'DIG-LEN': 24, 'EPL-RHO': 14, 'DIG-HIA': 8}
Full, lyric_and_other, errors by rule: {'NATURE/LEX-L': 64, 'NATURE/LEX-UNMARKED': 60, 'NATURE/LEX-S': 13, 'CONS-VOW/LEX-L': 7, 'EPL-INIT': 5, 'NATURE/ACC-PAROX-SHORT-AIOI': 3, 'COR-INT': 3, 'NATURE/NAT-EO': 2, 'CONS-VOW/NAT-EO': 2, 'POS-WORD': 1, 'NATURE/ACC-PAROX-SHORT': 1, 'POS-INIT': 1}
Full, iambic, errors by rule: {'NATURE/LEX-L': 97, 'NATURE/LEX-UNMARKED': 41, 'NATURE/LEX-S': 15, 'CONS-VOW/LEX-L': 15, 'CONS-VOW/ACC-PAROX-LONG': 8, 'MCL-WORD': 4, 'COR-INT': 3, 'NATURE/NAT-EO': 2, 'NATURE/ACC-PAROX-LONG': 2, 'NATURE/ACC-PROPERISP': 1, 'POS-ACROSS': 1, 'NATURE/NAT-CIRC': 1}

### F. Hand check (core only)

| Passage | Lines aligned | Fit | Scored positions | Decided | Correct | Ambiguous | Auto-detect top |
|---|---|---|---|---|---|---|---|
| sappho-1 | 27 | 27 | 208 | 154 | 154 | 54 | {'sapphic_hendecasyllable': 20, 'adonean': 7} |
| sappho-31 | 15 | 15 | 115 | 86 | 86 | 29 | {'sapphic_hendecasyllable': 11, 'adonean': 4} |
| alcaeus-346 | 4 | 4 | 52 | 35 | 35 | 17 | {'greater_asclepiad': 4} |
| sophocles-ot-1-15 | 15 | 15 | 121 | 93 | 92 | 28 | {'iambic_trimeter': 15} |
| archilochus-19 | 4 | 4 | 33 | 26 | 26 | 7 | {'iambic_trimeter': 4} |
Total: {'scored': 529, 'decided': 394, 'correct': 393, 'ambiguous': 135, 'decided_accuracy': 0.9975, 'ambiguous_share': 0.2552}
  disagreement sophocles-ot-1-15 {'line': 13, 'unit': 'οι', 'gold': 'S', 'scanner': 'L', 'p_long': 0.95, 'rule': 'COR-INT', 'vowel_rule': 'NAT-DIPH'}
Pindar: {'positions': 134, 'gold_positions': 122, 'conflicting_positions': 12, 'layer1': {'ambiguous': 70, 'right': 166}, 'responsion': {'resolved_right': 46, 'ambiguous_after': 24}, 'lines_with_unequal_units': 2} []
Prose: 119 {'certain short (0.0)': 34, 'certain long (1.0)': 57, 'ambiguous': 24, 'likely long (≥0.9)': 4} {'DICH-UNK': 14, 'COR-EXT': 7, 'MCL-WORD': 2, 'DIG-LEN': 1}

### F. Hand check (lexicon)

| Passage | Lines aligned | Fit | Scored positions | Decided | Correct | Ambiguous | Auto-detect top |
|---|---|---|---|---|---|---|---|
| sappho-1 | 27 | 27 | 208 | 188 | 186 | 20 | {'sapphic_hendecasyllable': 20, 'adonean': 7} |
| sappho-31 | 15 | 15 | 115 | 103 | 103 | 12 | {'sapphic_hendecasyllable': 11, 'adonean': 4} |
| alcaeus-346 | 4 | 4 | 52 | 50 | 48 | 2 | {'greater_asclepiad': 4} |
| sophocles-ot-1-15 | 15 | 15 | 121 | 111 | 110 | 10 | {'iambic_trimeter': 15} |
| archilochus-19 | 4 | 4 | 32 | 28 | 28 | 4 | {'iambic_trimeter': 4} |
Total: {'scored': 528, 'decided': 480, 'correct': 475, 'ambiguous': 48, 'decided_accuracy': 0.9896, 'ambiguous_share': 0.0909}
  disagreement sappho-1 {'line': 14, 'unit': 'ἀθ', 'gold': 'L', 'scanner': 'S', 'p_long': 0.1, 'rule': 'NATURE', 'vowel_rule': 'LEX-UNMARKED'}
  disagreement sappho-1 {'line': 27, 'unit': 'ἰμ', 'gold': 'L', 'scanner': 'S', 'p_long': 0.1, 'rule': 'NATURE', 'vowel_rule': 'LEX-UNMARKED'}
  disagreement alcaeus-346 {'line': 3, 'unit': 'άδ', 'gold': 'L', 'scanner': 'S', 'p_long': 0.1, 'rule': 'NATURE', 'vowel_rule': 'LEX-UNMARKED'}
  disagreement alcaeus-346 {'line': 4, 'unit': 'α κ', 'gold': 'S', 'scanner': 'L', 'p_long': 0.9, 'rule': 'NATURE', 'vowel_rule': 'LEX-L'}
  disagreement sophocles-ot-1-15 {'line': 13, 'unit': 'οι', 'gold': 'S', 'scanner': 'L', 'p_long': 0.95, 'rule': 'COR-INT', 'vowel_rule': 'NAT-DIPH'}
Pindar: {'positions': 134, 'gold_positions': 122, 'conflicting_positions': 12, 'layer1': {'ambiguous': 16, 'right': 217, 'wrong': 3}, 'responsion': {'resolved_right': 13, 'ambiguous_after': 3}, 'lines_with_unequal_units': 2} [{'line': 2, 'side': 'antistrophe', 'unit': 'ασ', 'gold': 'L', 'scanner': 'S', 'rule': 'NATURE'}, {'line': 7, 'side': 'antistrophe', 'unit': 'ίσ', 'gold': 'S', 'scanner': 'L', 'rule': 'NATURE'}, {'line': 7, 'side': 'antistrophe', 'unit': 'ίκ', 'gold': 'L', 'scanner': 'S', 'rule': 'NATURE'}]
Prose: 119 {'certain short (0.0)': 34, 'certain long (1.0)': 57, 'ambiguous': 9, 'likely long (≥0.9)': 6, 'likely short (≤0.1)': 13} {'COR-EXT': 4, 'DIG-LEN': 2, 'LEX-CONFLICT': 2, 'MCL-WORD': 1}
