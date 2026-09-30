# Indexed corpus coverage

Index snapshot: 2026-09-30T09:53:26Z. The accepted SQLite index contains 287,536 records across 101 exact author labels. 98,243 records meet the clean Greek text search filter.

A record is not necessarily a unique fragment, composition, or independent witness. Multiple editions and translations can repeat a passage. The complete SQL-derived counts by author, quality, language, kind, and source are in [`coverage.json`](../data/reports/coverage.json).

"Clean Greek text" means `kind=text`, `language=grc`, and `quality=source_text`. It is a search eligibility label; edition text may contain editorial supplements.

## Accepted records by source

| Source label | Records |
| --- | ---: |
| commentary | 326 |
| lyra | 2,460 |
| lyric_web | 102 |
| ogc | 258,548 |
| ogc_derived | 638 |
| p2_alcaeus | 157 |
| p2_editions | 203 |
| p2_elegy | 327 |
| p2_grammar | 22 |
| p2_ibycus | 19 |
| p2_melic | 2 |
| p2_ogc | 481 |
| p2_perseus | 5,994 |
| p2_perseus_notes | 91 |
| p2_scholarship | 123 |
| p2_stesichorus | 101 |
| perseus | 14,706 |
| reception | 589 |
| sappho | 2,647 |

## Core requested names: exact labels only

These rows match stored author labels only by case-insensitive exact spelling. They do not merge transliterations, titles, uncertain attributions, or Greek labels. A dash means no exact label match, not zero coverage.

| Requested name | Matched source labels | Clean Greek text records | Commentary / reference records |
| --- | --- | ---: | ---: |
| Ibycus | `Ibycus` | 5 | 16 |
| Alcaeus | `Alcaeus` | 0 | 32 |
| Sappho | `Sappho`, `sappho` | 582 | 20 |
| Pindar | `Pindar` | 167 | 54 |
| Bacchylides | `Bacchylides`, `bacchylides` | 1,376 | 73 |
| Alcman | `Alcman` | 0 | 11 |
| Stesichorus | `Stesichorus` | 2 | 10 |
| Simonides | `Simonides` | 0 | 9 |
| Anacreon | `Anacreon` | 0 | 5 |
| Archilochus | `Archilochus` | 0 | 34 |
| Mimnermus | — | — | — |
| Solon | — | — | — |
| Hipponax | `hipponax` | 3 | 0 |
| Theognis | — | — | — |
| Semonides | — | — | — |
| Timotheus | — | — | — |
| Corinna | — | — | — |
| Homer | `Homer` | 1,431 | 2 |
| Hesiod | `Hesiod` | 104 | 1 |
| Homeric Hymns | `Homeric Hymns` | 2 | 0 |

## Additional Greek-script source labels

These source labels are reported separately. The script does not assign them to an English author name.

| Exact source label | Clean Greek text records | Other text records | Commentary / reference records |
| --- | ---: | ---: | ---: |
| Αλκμάν | 4 | 0 | 0 |
| Ανακρέων | 6 | 0 | 0 |
| Αρχίλοχος | 51 | 0 | 0 |
| Κόριννα | 7 | 0 | 17 |
| Μίμνερμος | 8 | 0 | 0 |
| Σιμωνίδης ο Κείος | 4 | 0 | 0 |
| Στησίχορος | 5 | 0 | 0 |

## Similar spellings in source labels

These are string matches for discovery only. Their records are not added to the exact-name counts above.

| Requested name | Other source labels containing that spelling |
| --- | --- |
| Alcaeus | `Alcaeus of Messene / Anthologia Palatina`, `Alcaeus of Mytilene`, `Euripides / Alcaeus / Anacreon`, `Sappho / Alcaeus` |
| Sappho | `Sappho / Alcaeus` |
| Pindar | `Bacchylides / Pindarus`, `Bacchylides / Simonides / Pindarus`, `Pindar Scholia`, `Pindarus`, `Scholia in Pindarum`, `Simonides / Pindarus`, `Vitae Pindari et varia de Pindaro`, `pindarus`, `scholia-in-pindarum`, `vitae-pindari-et-varia-de-pindaro` |
| Bacchylides | `Bacchylides / Pindarus`, `Bacchylides / Simonides`, `Bacchylides / Simonides / Pindarus` |
| Simonides | `Bacchylides / Simonides`, `Bacchylides / Simonides / Pindarus`, `Simonides / Pindarus`, `simonides-ceus` |
| Anacreon | `Anacreon (Wikisource attribution)`, `Euripides / Alcaeus / Anacreon`, `Pseudo- Anacreon`, `anacreontea` |
| Archilochus | `Archilochus / Hipponax`, `Euripides / Archilochus` |
| Hipponax | `Archilochus / Hipponax` |
| Theognis | `theognis-elegy` |
| Homer | `Homeric Hymns`, `certamen-homeri-et-hesiodi`, `homerica`, `homerus-epic`, `hymni-homerici`, `scholia-in-homerum`, `vitae-homeri` |
| Hesiod | `certamen-homeri-et-hesiodi`, `hesiodus`, `scholia-in-hesiodum`, `vitae-hesiodi-particula` |

## Limits

The index includes reference, OCR, mixed, and review-needed records that are excluded from ordinary clean-text search. Source author labels can be inconsistent or disputed. Similar labels in separate sources do not prove distinct witnesses. Coverage reports what the accepted index contains; it cannot establish comprehensive surviving-text coverage.
