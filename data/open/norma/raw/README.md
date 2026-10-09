---
license: gpl-3.0
configs:
- config_name: default
  data_files:
  - split: test
    path: data/test.jsonl
  - split: validation
    path: data/validation.jsonl
---
# Norma Syllabarum Graecarum - A Benchmark for grc Syllabification and Vowel Length Annotation

We introduce *Norma* as a common benchmark for the evaluation and comparison of NLP tools concerning markup of two tasks for Ancient Greek (grc): (1) **vowel length** of dichronic vowels (alpha, iota, ypsilon) in open syllables (where they impact syllable weight) and (2) **syllabification**, both boundaries and weight. This means that the benchmark also indirectly tests handling of sandhi phenomena and, for verse, metre.

The benchmark includes 1228 lines of text by each of the below 14 authors, spanning many periods and genres of both verse and prose:

- Alcman (*Louvre Partheneion* 36-49, mix of aeolic, trochaic and dactylic cola, NB: contains digamma, ϝ)
- Bacchylides (*Epinikion 5*, anapaesto-iambic and dactylo-troachaic)
- Aeschylus (*Supplices* 1-10, anapaests)
- Sophocles (*Oedipus Tyrannus* 1-20, iambic trimeter)
- Euripides (*Bacchae* 1-20, iambic trimeter)
- Thucydides (*Thucydidis historiae* 1.1.1.1-1.2.2.1, prose)
- Aristophanes (*Acharnenses* 1-16, iambic trimeter, and 299 lines from responding lyric songs)
- Plato (*Cratylus* 383-384a5, prose)
- Dioscorides (*Anthologia Graeca* 5.55, elegiac distichs)
- Plutarch (*Stoicos absurdiora poetis dicere* 1057.C1-F1, prose)
- Epictetus (*Enchiridion* 1.1.1-1.5.1, prose)
- Origenes (*Contra Celsum* 1.1-1.20, prose)
- Nonnus (*Dionysiaca* 1-20, dactylic hexameter)
- Quintus (*Posthomerica* 1-20, dactylic hexameter)

The repository also provides a validation set, [`data/validation.jsonl`](data/validation.jsonl), containing 764 lines from Aristophanes' lyric poetry for the macronization task.

## Markup Format

For the syllabification task the markup is:

- square brackets [] enclose heavy syllables
- curly brackets {} enclose light syllables

and for the macronization task the markup is:

- carets ^ follow short ambiguous vowels (α, ι, υ)
- underscores _ follow long ambiguous vowels (α, ι, υ).

In prose, for ease of comparison we consider the sentence to be the equivalent of the verse line, with the consequence that the final syllable of a sentence will be considered heavy if it ends with a consonant, even though the following sentence begins with a vowel; i.e. a prose *brevis in longo*.

With regard to vowel length, the benchmark is designed to test performance of open (light) syllables only. This means that *all* open syllables with ambiguous vowels (α, ι, υ) have them marked with carets or underscores, while this is only *sporadically* true for closed syllables (and in such cases mostly before mute-liquid clusters).

We also have an example of a word that avoids the normal rules of syllabification:

- ...[ῇ]**{σι^ }{Σκα^}**[μάν][δρου,] (*Posthomerica*, 10)

