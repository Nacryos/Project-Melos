# Independent audit: retained-source LSJ definition extraction

## Verdict: PASS for the reviewed narrow change

Module: `backend/lexicon_senses.py`

SHA-256: `0653b2b6c0561b440185fc44fba4d8d3c5110450093e19e346c1a3ac186324f5`

This is a retained-source parser audit, not a claim of universal dictionary or contextual interpretation accuracy. No external sources were fetched, no corpus records were edited, and no definitions were authored by the auditor.

## Checks

- PASS: retained eng5, eng17, and eng21 XML SHA-256 values match their archived records.
- PASS: exact source offsets reproduce every accepted definition in the 300-record sample: 422 current spans, versus 416 baseline spans.
- PASS: all 58 extracted crossreferences in that sample reproduce their source target spans. They remain unresolved evidence, not merged meanings; no private entity placeholders were found in their target keys.
- PASS: six sample records gain one genuine core definition apiece; the other 294 records have identical accepted/excluded projections apart from method-version IDs omitted from the comparison.
- PASS: 90 tests across test_lyric_dictionary_gaps.py, test_lexicon_senses.py, test_lexicon_render.py, test_candidate_senses.py, and test_interlinear.py.
- PASS: epsilon-core entry lsj:5:n44560 now yields the literal source definition 'well-disposed, kindly, friendly'. Unrelated example translations remain excluded.
- PASS: lsj:21:n96270 restores 'placing, setting' and 'standing still, stationariness'; political definitions were already present. This does not itself rank the correct contextual sense.
- PASS: lsj:17:n79904 retains its same 22 accepted spans; homographic lsj:17:n79905 retains zero English definitions and an unresolved source crossreference to pai=s. No cross-entry meaning merge occurs.

## Adversarial finding fixed before acceptance

The first proposal reset previous-example detection at every new sense. The seeded sample exposed lsj:13:n68949, where the raw TEI puts a complete Greek example before the sense wrapper; this incorrectly promoted its translation into a lemma definition. The auditor blocked that proposal. The accepted revision skips only explicit preamble morphology wrappers and retains that exclusion. It also restricts completed-parenthetical exceptions to explicit marginal/variant-reading notes; the frog-colour usage in lsj:2:n19632 remains excluded from the generic lemma definition.

## Source artifact hashes

- eng5: `2e0ef90281c62e320f5386364b875f1000d1bcb22718369a5dbe0b6c68d5ad95`
- eng17: `237bf71d5e293c8cd5bc6c22e125e180cb11f28597b17c2efe0f9018c03e1fcc`
- eng21: `c377dcf36490493b05a0543112b77bdc286855448b0903381eb4869d0806805c`

All reside beneath data/raw/lexica/lsj/CTS_XML_TEI/perseus/pdllex/grc/lsj/ as grc.lsj.perseus-engN.xml. Source URLs in archived records point to the pinned PerseusDL lexica revision 56061ca127f4a2844980baffc5f2b6d1332897b3.

## Reproducible sample

Read data/lexica/entries.jsonl in file order; keep source == 'PerseusDL LSJ TEI'; take random.Random(7990444560).sample(records, 300). Compare ordered accepted text/node_path/start/end and ordered exclusions. Offsets are uncompacted Greek-span-rendered TEI offsets. Baseline was captured before this task's parser edit. The following ledger preserves every sampled record and accepted-span count, not a selected subset.

| Record | Baseline | Accepted revision | Changed projection |
| --- | ---: | ---: | --- |
| lsj:1:n1845 | 2 | 2 | no |
| lsj:20:n92460 | 1 | 1 | no |
| lsj:4:n23871 | 1 | 1 | no |
| lsj:26:n115876 | 4 | 4 | no |
| lsj:14:n71291 | 0 | 0 | no |
| lsj:17:n80433 | 2 | 2 | no |
| lsj:23:n107118 | 0 | 0 | no |
| lsj:21:n96816 | 0 | 0 | no |
| lsj:1:n319 | 0 | 0 | no |
| lsj:11:n55434 | 1 | 1 | no |
| lsj:17:n80796 | 1 | 1 | no |
| lsj:5:n45278 | 0 | 0 | no |
| lsj:2:n21206 | 1 | 1 | no |
| lsj:4:n27143 | 1 | 1 | no |
| lsj:5:n33643 | 1 | 1 | no |
| lsj:16:n73357 | 0 | 0 | no |
| lsj:5:n38324 | 1 | 1 | no |
| lsj:1:n12348 | 6 | 7 | yes |
| lsj:11:n56233 | 1 | 2 | yes |
| lsj:11:n56755 | 1 | 1 | no |
| lsj:11:n58447 | 1 | 1 | no |
| lsj:10:n50080 | 1 | 1 | no |
| lsj:11:n56179 | 0 | 0 | no |
| lsj:17:n83089 | 0 | 0 | no |
| lsj:8:n46832 | 1 | 1 | no |
| lsj:4:n24990 | 1 | 1 | no |
| lsj:13:n68987 | 4 | 4 | no |
| lsj:11:n51844 | 0 | 0 | no |
| lsj:24:n111038 | 1 | 1 | no |
| lsj:11:n53576 | 1 | 1 | no |
| lsj:17:n83740 | 3 | 3 | no |
| lsj:17:n83734 | 1 | 1 | no |
| lsj:23:n109063 | 1 | 1 | no |
| lsj:13:n67602 | 3 | 3 | no |
| lsj:11:n52123 | 1 | 1 | no |
| lsj:12:n63263 | 1 | 1 | no |
| lsj:8:n46993 | 1 | 1 | no |
| lsj:1:n13257 | 1 | 1 | no |
| lsj:25:n114070 | 0 | 0 | no |
| lsj:23:n109182 | 1 | 1 | no |
| lsj:1:n15708 | 1 | 1 | no |
| lsj:4:n24856 | 11 | 11 | no |
| lsj:5:n35813 | 3 | 3 | no |
| lsj:11:n53804 | 0 | 0 | no |
| lsj:17:n78934 | 3 | 3 | no |
| lsj:3:n22569 | 2 | 2 | no |
| lsj:23:n107474 | 1 | 1 | no |
| lsj:17:n82454 | 3 | 3 | no |
| lsj:22:n102998 | 0 | 0 | no |
| lsj:17:n87766 | 1 | 1 | no |
| lsj:16:n72427 | 1 | 1 | no |
| lsj:1:n14690 | 0 | 0 | no |
| lsj:16:n71929 | 0 | 0 | no |
| lsj:1:n7383 | 1 | 1 | no |
| lsj:16:n73016 | 1 | 1 | no |
| lsj:22:n103065 | 2 | 2 | no |
| lsj:17:n89269 | 2 | 2 | no |
| lsj:5:n30224 | 2 | 2 | no |
| lsj:1:n2863 | 2 | 2 | no |
| lsj:24:n112648 | 1 | 1 | no |
| lsj:3:n21958 | 1 | 1 | no |
| lsj:21:n100654 | 0 | 0 | no |
| lsj:13:n65613 | 1 | 1 | no |
| lsj:21:n98704 | 17 | 17 | no |
| lsj:21:n97508 | 1 | 1 | no |
| lsj:16:n72914 | 1 | 1 | no |
| lsj:9:n47950 | 1 | 1 | no |
| lsj:1:n6842 | 1 | 1 | no |
| lsj:21:n98698 | 1 | 1 | no |
| lsj:4:n26248 | 1 | 1 | no |
| lsj:16:n74808 | 0 | 0 | no |
| lsj:13:n68556 | 1 | 1 | no |
| lsj:5:n34875 | 1 | 1 | no |
| lsj:5:n34602 | 0 | 0 | no |
| lsj:16:n74496 | 1 | 1 | no |
| lsj:17:n83911 | 0 | 0 | no |
| lsj:17:n89265 | 1 | 1 | no |
| lsj:24:n111256 | 0 | 0 | no |
| lsj:17:n88828 | 2 | 2 | no |
| lsj:11:n57138 | 2 | 2 | no |
| lsj:3:n21660 | 1 | 1 | no |
| lsj:26:n115412 | 1 | 1 | no |
| lsj:5:n41095 | 1 | 1 | no |
| lsj:1:n18436 | 5 | 5 | no |
| lsj:13:n68980 | 3 | 3 | no |
| lsj:1:n14312 | 1 | 1 | no |
| lsj:1:n18245 | 0 | 0 | no |
| lsj:1:n2023 | 1 | 1 | no |
| lsj:4:n25716 | 1 | 1 | no |
| lsj:4:n27140 | 0 | 0 | no |
| lsj:5:n40496 | 0 | 0 | no |
| lsj:5:n43425 | 1 | 1 | no |
| lsj:23:n109117 | 1 | 1 | no |
| lsj:12:n62660 | 1 | 1 | no |
| lsj:2:n21231 | 1 | 1 | no |
| lsj:17:n80313 | 2 | 2 | no |
| lsj:17:n86290 | 0 | 0 | no |
| lsj:21:n101426 | 1 | 1 | no |
| lsj:20:n92071 | 1 | 1 | no |
| lsj:26:n115313 | 3 | 3 | no |
| lsj:21:n98128 | 1 | 1 | no |
| lsj:17:n77877 | 1 | 1 | no |
| lsj:16:n72419 | 0 | 0 | no |
| lsj:13:n67739 | 1 | 1 | no |
| lsj:2:n19703 | 1 | 1 | no |
| lsj:9:n48264 | 1 | 1 | no |
| lsj:5:n31903 | 2 | 2 | no |
| lsj:1:n11241 | 2 | 2 | no |
| lsj:4:n28019 | 1 | 1 | no |
| lsj:13:n68949 | 0 | 0 | no |
| lsj:17:n91064 | 1 | 1 | no |
| lsj:17:n90765 | 1 | 1 | no |
| lsj:5:n37837 | 1 | 1 | no |
| lsj:17:n82845 | 2 | 2 | no |
| lsj:21:n101489 | 1 | 1 | no |
| lsj:17:n82551 | 1 | 1 | no |
| lsj:11:n51823 | 0 | 0 | no |
| lsj:17:n79050 | 1 | 1 | no |
| lsj:1:n5001 | 7 | 7 | no |
| lsj:4:n26349 | 1 | 1 | no |
| lsj:11:n60249 | 1 | 1 | no |
| lsj:3:n21477 | 0 | 0 | no |
| lsj:5:n45520 | 1 | 1 | no |
| lsj:17:n84015 | 0 | 0 | no |
| lsj:1:n11665 | 1 | 1 | no |
| lsj:11:n60213 | 2 | 2 | no |
| lsj:23:n109379 | 1 | 1 | no |
| lsj:1:n18609 | 1 | 1 | no |
| lsj:24:n110572 | 1 | 1 | no |
| lsj:21:n97991 | 1 | 1 | no |
| lsj:11:n57295 | 1 | 1 | no |
| lsj:17:n82798 | 1 | 1 | no |
| lsj:4:n23260 | 1 | 1 | no |
| lsj:17:n86027 | 0 | 0 | no |
| lsj:17:n77507 | 1 | 1 | no |
| lsj:5:n30990 | 1 | 1 | no |
| lsj:5:n41489 | 2 | 2 | no |
| lsj:17:n87480 | 1 | 1 | no |
| lsj:24:n111346 | 1 | 1 | no |
| lsj:1:n8330 | 2 | 2 | no |
| lsj:21:n97798 | 1 | 1 | no |
| lsj:17:n91200 | 0 | 0 | no |
| lsj:17:n83060 | 1 | 1 | no |
| lsj:13:n65440 | 3 | 3 | no |
| lsj:5:n45721 | 1 | 1 | no |
| lsj:26:n115448 | 1 | 1 | no |
| lsj:3:n22354 | 1 | 1 | no |
| lsj:12:n63545 | 1 | 1 | no |
| lsj:1:n18539 | 1 | 1 | no |
| lsj:1:n16149 | 1 | 1 | no |
| lsj:23:n107212 | 1 | 1 | no |
| lsj:17:n84116 | 0 | 0 | no |
| lsj:1:n15696 | 0 | 0 | no |
| lsj:23:n109260 | 1 | 1 | no |
| lsj:16:n72780 | 1 | 1 | no |
| lsj:17:n81309 | 7 | 7 | no |
| lsj:17:n77004 | 1 | 1 | no |
| lsj:17:n81743 | 1 | 1 | no |
| lsj:20:n92794 | 0 | 0 | no |
| lsj:1:n10344 | 3 | 3 | no |
| lsj:13:n67628 | 1 | 1 | no |
| lsj:23:n109110 | 1 | 1 | no |
| lsj:5:n43242 | 1 | 1 | no |
| lsj:4:n29049 | 1 | 1 | no |
| lsj:21:n101345 | 0 | 0 | no |
| lsj:2:n20517 | 0 | 0 | no |
| lsj:5:n32346 | 0 | 0 | no |
| lsj:5:n36792 | 4 | 4 | no |
| lsj:4:n27167 | 0 | 0 | no |
| lsj:12:n61428 | 1 | 1 | no |
| lsj:11:n56127 | 0 | 0 | no |
| lsj:17:n90360 | 1 | 1 | no |
| lsj:1:n121 | 0 | 0 | no |
| lsj:4:n25003 | 11 | 11 | no |
| lsj:21:n101775 | 2 | 2 | no |
| lsj:11:n55230 | 1 | 1 | no |
| lsj:17:n85813 | 1 | 1 | no |
| lsj:23:n107606 | 6 | 6 | no |
| lsj:5:n43586 | 3 | 3 | no |
| lsj:1:n15932 | 0 | 0 | no |
| lsj:23:n107973 | 1 | 1 | no |
| lsj:14:n70498 | 1 | 1 | no |
| lsj:21:n97862 | 1 | 1 | no |
| lsj:21:n101613 | 0 | 0 | no |
| lsj:5:n35389 | 1 | 1 | no |
| lsj:11:n58458 | 1 | 2 | yes |
| lsj:2:n20069 | 5 | 5 | no |
| lsj:11:n59611 | 1 | 1 | no |
| lsj:17:n77996 | 1 | 1 | no |
| lsj:1:n4762 | 0 | 0 | no |
| lsj:17:n82622 | 0 | 0 | no |
| lsj:12:n62181 | 2 | 2 | no |
| lsj:3:n21782 | 0 | 0 | no |
| lsj:4:n29761 | 0 | 0 | no |
| lsj:17:n82476 | 1 | 1 | no |
| lsj:17:n86133 | 1 | 1 | no |
| lsj:10:n49905 | 2 | 2 | no |
| lsj:11:n54771 | 0 | 0 | no |
| lsj:21:n97166 | 5 | 5 | no |
| lsj:3:n22339 | 5 | 5 | no |
| lsj:17:n76923 | 2 | 2 | no |
| lsj:1:n1156 | 1 | 1 | no |
| lsj:21:n100377 | 0 | 0 | no |
| lsj:16:n74412 | 0 | 0 | no |
| lsj:5:n44556 | 1 | 1 | no |
| lsj:1:n6311 | 1 | 1 | no |
| lsj:17:n88298 | 0 | 0 | no |
| lsj:1:n8400 | 1 | 1 | no |
| lsj:4:n25988 | 1 | 1 | no |
| lsj:1:n12661 | 1 | 1 | no |
| lsj:1:n18642 | 3 | 3 | no |
| lsj:21:n93318 | 0 | 0 | no |
| lsj:16:n73373 | 0 | 0 | no |
| lsj:16:n71885 | 3 | 3 | no |
| lsj:1:n6907 | 0 | 0 | no |
| lsj:17:n77482 | 1 | 1 | no |
| lsj:5:n42495 | 1 | 1 | no |
| lsj:1:n11266 | 0 | 0 | no |
| lsj:23:n106231 | 1 | 1 | no |
| lsj:24:n111070 | 1 | 1 | no |
| lsj:11:n51841 | 1 | 1 | no |
| lsj:1:n5278 | 1 | 1 | no |
| lsj:24:n110117 | 3 | 3 | no |
| lsj:22:n104393 | 1 | 1 | no |
| lsj:13:n69071 | 2 | 2 | no |
| lsj:1:n16012 | 4 | 4 | no |
| lsj:1:n11733 | 1 | 1 | no |
| lsj:21:n96793 | 1 | 1 | no |
| lsj:1:n1341 | 1 | 1 | no |
| lsj:5:n30181 | 2 | 2 | no |
| lsj:4:n25926 | 2 | 2 | no |
| lsj:5:n37379 | 0 | 0 | no |
| lsj:13:n66347 | 1 | 1 | no |
| lsj:15:n71515 | 2 | 2 | no |
| lsj:1:n11468 | 0 | 0 | no |
| lsj:17:n85437 | 1 | 1 | no |
| lsj:11:n60915 | 0 | 0 | no |
| lsj:25:n113947 | 0 | 0 | no |
| lsj:5:n37585 | 2 | 2 | no |
| lsj:8:n46695 | 2 | 2 | no |
| lsj:22:n105627 | 3 | 3 | no |
| lsj:14:n71156 | 0 | 0 | no |
| lsj:16:n74551 | 1 | 1 | no |
| lsj:2:n19632 | 0 | 1 | yes |
| lsj:11:n53676 | 1 | 1 | no |
| lsj:11:n54516 | 3 | 3 | no |
| lsj:5:n36932 | 1 | 1 | no |
| lsj:24:n112110 | 0 | 0 | no |
| lsj:1:n11449 | 2 | 2 | no |
| lsj:2:n19177 | 1 | 1 | no |
| lsj:17:n84915 | 2 | 2 | no |
| lsj:17:n86596 | 1 | 1 | no |
| lsj:17:n85195 | 3 | 3 | no |
| lsj:16:n73784 | 1 | 1 | no |
| lsj:23:n106505 | 1 | 1 | no |
| lsj:14:n70463 | 1 | 1 | no |
| lsj:17:n87382 | 1 | 1 | no |
| lsj:25:n113096 | 2 | 2 | no |
| lsj:11:n53575 | 2 | 2 | no |
| lsj:5:n44429 | 5 | 5 | no |
| lsj:27:n116316 | 0 | 0 | no |
| lsj:11:n59023 | 1 | 1 | no |
| lsj:1:n4812 | 1 | 1 | no |
| lsj:17:n78033 | 0 | 0 | no |
| lsj:5:n38786 | 1 | 1 | no |
| lsj:5:n44497 | 2 | 2 | no |
| lsj:1:n7572 | 0 | 0 | no |
| lsj:12:n62229 | 1 | 1 | no |
| lsj:24:n111387 | 1 | 1 | no |
| lsj:4:n28202 | 0 | 0 | no |
| lsj:13:n67626 | 2 | 2 | no |
| lsj:21:n95764 | 0 | 0 | no |
| lsj:21:n96395 | 1 | 1 | no |
| lsj:5:n32151 | 1 | 1 | no |
| lsj:1:n7208 | 3 | 3 | no |
| lsj:21:n93618 | 1 | 1 | no |
| lsj:3:n22100 | 10 | 10 | no |
| lsj:1:n15853 | 0 | 0 | no |
| lsj:4:n29132 | 1 | 1 | no |
| lsj:21:n97678 | 1 | 1 | no |
| lsj:13:n65364 | 2 | 2 | no |
| lsj:13:n65815 | 0 | 1 | yes |
| lsj:21:n100686 | 1 | 1 | no |
| lsj:17:n76858 | 0 | 0 | no |
| lsj:20:n92307 | 1 | 1 | no |
| lsj:13:n64572 | 0 | 0 | no |
| lsj:1:n1406 | 1 | 1 | no |
| lsj:2:n19123 | 15 | 15 | no |
| lsj:17:n77086 | 2 | 2 | no |
| lsj:1:n2775 | 1 | 1 | no |
| lsj:23:n106792 | 5 | 6 | yes |
| lsj:16:n74744 | 1 | 1 | no |
| lsj:11:n58797 | 3 | 3 | no |
| lsj:2:n20020 | 0 | 0 | no |
| lsj:1:n10012 | 0 | 0 | no |
| lsj:2:n21036 | 1 | 1 | no |
| lsj:1:n11595 | 1 | 1 | no |
| lsj:1:n12591 | 1 | 1 | no |
| lsj:1:n14500 | 1 | 1 | no |
| lsj:5:n33985 | 1 | 1 | no |

## Exact added spans in the six changed sample records

- lsj:1:n12348: `/entryFree/sense[1]/tr[1]`, offsets 203:235, "to be away from, have no part in"
- lsj:11:n56233: `/entryFree/sense/tr[1]`, offsets 73:84, "thick cloak"
- lsj:11:n58458: `/entryFree/sense[1]/tr`, offsets 66:94, "doum-palm, Hyphaene thebaica"
- lsj:2:n19632: `/entryFree/sense/tr[1]`, offsets 70:95, "of or belonging to a frog"
- lsj:13:n65815: `/entryFree/sense/tr`, offsets 82:126, "with a garment embroidered with black leaves"
- lsj:23:n106792: `/entryFree/sense[1]/tr[1]`, offsets 269:276, "dictate"
## Limits

Sampling does not establish global error-free extraction. Other source layouts still conservatively produce missing definitions. This patch recovers literal dictionary evidence; it does not solve contextual sense ranking, syntax disambiguation, or unattested dialect forms. No source-download or deployment audit is claimed here.

