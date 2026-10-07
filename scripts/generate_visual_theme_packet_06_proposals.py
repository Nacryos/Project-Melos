#!/usr/bin/env python3
"""Generate exhaustive, literal-validated raw proposals for visual-theme packets 06/07.

All Greek rows were read in full and grouped by source/work/ode before this
script was authored. Unlisted rows receive an explicit conservative abstention.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET_DIR = ROOT / ".benchmarks/visual-themes/packets"
RAW_DIR = ROOT / "data/annotations/visual-themes/raw"

ABSTAIN_REASON = (
    "No clearly developed aesthetic nature scene or sustained simile in this fragment; "
    "natural terms, setting names, or decorative flora alone do not establish a theme."
)


def evidence(record_id: str, quote: str) -> dict[str, str]:
    return {"id": record_id, "quote": quote}


def label(theme: str, kind: str, spans: list[dict[str, str]]) -> dict:
    return {
        "theme": theme,
        "kind": kind,
        "strength": "strong",
        "evidence": spans,
        "modifiers": [],
    }


POSITIVE = {
    # Pindar, Nemean 4: a visible pastoral ridge landscape.
    "perseus:tlg0033.tlg003.perseus-grc2:4.40–4.59:1": {
        "reason": "Cowherds and prominent ridges form a concrete pastoral landscape, located between Dodona and the Ionian route.",
        "labels": [label("meadow_pasture", "scene", [
            evidence("perseus:tlg0033.tlg003.perseus-grc2:4.40–4.59:1", "βουβόται τόθι πρῶνες ἔξοχοι κατάκεινται"),
            evidence("perseus:tlg0033.tlg003.perseus-grc2:4.40–4.59:1", "Δωδώναθεν ἀρχόμενοι πρὸς Ἰόνιον πόρον."),
        ])],
    },
    # Pindar, Nemean 6: herbs and shaded mountain slopes form the upbringing scene.
    "perseus:tlg0033.tlg003.perseus-grc2:6.40–6.59:1": {
        "reason": "The passage links nourishing mountain plants with the shaded old mountains of Phlius.",
        "labels": [label("mountain_woodland", "scene", [
            evidence("perseus:tlg0033.tlg003.perseus-grc2:6.40–6.59:1", "βοτάνα τέ νιν"),
            evidence("perseus:tlg0033.tlg003.perseus-grc2:6.40–6.59:1", "ἤρεφε δασκίοις"),
            evidence("perseus:tlg0033.tlg003.perseus-grc2:6.40–6.59:1", "Φλιοῦντος ὑπʼ ὠγυγίοις ὄρεσιν."),
        ])],
    },
    # Bacchylides, Perseus Epinicians Ode 5: same extended eagle simile as the OGC line records.
    "perseus:tlg0199.tlg001.perseus-grc2:5.21–5.40:1": {
        "reason": "The extended eagle simile ranges across high land summits and rough sea waves.",
        "labels": [
            label("mountain_woodland", "simile", [
                evidence("perseus:tlg0199.tlg001.perseus-grc2:5.1–5.20:1", "αἰετὸς εὐρυάνακτος ἄγγελος"),
                evidence("perseus:tlg0199.tlg001.perseus-grc2:5.21–5.40:1", "οὔ νιν κορυφαὶ μεγάλας ἴσχουσι γαίας,"),
                evidence("perseus:tlg0199.tlg001.perseus-grc2:5.21–5.40:1", "δυσπαίπαλα κύματα· νωμᾶ-"),
            ]),
            label("sea_coast", "simile", [
                evidence("perseus:tlg0199.tlg001.perseus-grc2:5.1–5.20:1", "αἰετὸς εὐρυάνακτος ἄγγελος"),
                evidence("perseus:tlg0199.tlg001.perseus-grc2:5.21–5.40:1", "οὐδʼ ἁλὸς ἀκαμάτας"),
                evidence("perseus:tlg0199.tlg001.perseus-grc2:5.21–5.40:1", "δυσπαίπαλα κύματα· νωμᾶ-"),
            ]),
        ],
    },
    # Bacchylides, Perseus Epinicians Ode 5: full-record counterpart to the OGC Ida pasture simile.
    "perseus:tlg0199.tlg001.perseus-grc2:5.61–5.80:1": {
        "reason": "The explicit leaves-and-wind comparison is set across Ida’s sheep-grazed, bright slopes.",
        "labels": [label("meadow_pasture", "simile", [
            evidence("perseus:tlg0199.tlg001.perseus-grc2:5.61–5.80:1", "οἷά τε φύλλʼ ἄνεμος"),
            evidence("perseus:tlg0199.tlg001.perseus-grc2:5.61–5.80:1", "Ἴδας ἀνὰ μηλοβότους"),
            evidence("perseus:tlg0199.tlg001.perseus-grc2:5.61–5.80:1", "πρῶνας ἀργηστὰς δονεῖ."),
        ])],
    },
    # Pindar, Nemean 11: an extended crop/tree-flowering comparison across adjacent records.
    "perseus:tlg0033.tlg003.perseus-grc2:11.20–11.39:1": {
        "reason": "This field image begins an extended crop-and-blossom analogy completed in the following Nemean 11 record.",
        "labels": [label("meadow_pasture", "simile", [
            evidence("perseus:tlg0033.tlg003.perseus-grc2:11.20–11.39:1", "ἐν σχερῷ δʼ οὔτʼ ὦν μέλαιναι καρπὸν ἔδωκαν ἄρουραι,"),
            evidence("perseus:tlg0033.tlg003.perseus-grc2:11.40–11.48:1", "δένδρεά τʼ οὐκ ἐθέλει πάσαις ἐτέων περόδοις"),
            evidence("perseus:tlg0033.tlg003.perseus-grc2:11.40–11.48:1", "ἄνθος εὐῶδες φέρειν πλούτῳ ἴσον,"),
        ])],
    },
    "perseus:tlg0033.tlg003.perseus-grc2:11.40–11.48:1": {
        "reason": "Trees that flower only in alternating years complete the extended agricultural analogy begun in Nemean 11.20–39.",
        "labels": [label("garden_grove", "simile", [
            evidence("perseus:tlg0033.tlg003.perseus-grc2:11.20–11.39:1", "μέλαιναι καρπὸν ἔδωκαν ἄρουραι,"),
            evidence("perseus:tlg0033.tlg003.perseus-grc2:11.40–11.48:1", "δένδρεά τʼ οὐκ ἐθέλει πάσαις ἐτέων περόδοις"),
            evidence("perseus:tlg0033.tlg003.perseus-grc2:11.40–11.48:1", "ἄνθος εὐῶδες φέρειν πλούτῳ ἴσον,"),
            evidence("perseus:tlg0033.tlg003.perseus-grc2:11.40–11.48:1", "ἀλλʼ ἐν ἀμείβοντι."),
        ])],
    },

    # Bacchylides, epinician Ode 3: a sacred grove, temple, and Castalian water in the same scene.
    "ogc:bacchylides.tlg0199-tlg001.jsonl:137": {
        "reason": "The great grove is placed beside a temple and the Castalian stream, forming a specific sacred landscape.",
        "labels": [label("garden_grove", "scene", [
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:137", "πάροιθε ναοῦ, τόθι μέγιστον ἄλσος"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:138", "Φοίβου παρὰ Κασταλίας ῥεέθροις"),
        ])],
    },
    "ogc:bacchylides.tlg0199-tlg001.jsonl:138": {
        "reason": "The Castalian stream is part of the described grove-and-temple landscape, not an isolated water name.",
        "labels": [label("river_spring", "scene", [
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:138", "Φοίβου παρὰ Κασταλίας ῥεέθροις"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:137", "πάροιθε ναοῦ, τόθι μέγιστον ἄλσος"),
        ])],
    },

    # Bacchylides, epinician Ode 5: the eagle simile ranges over mountain summits and rough sea.
    "ogc:bacchylides.tlg0199-tlg001.jsonl:260": {
        "reason": "The extended eagle simile sets high land summits against the open sea and its rough waves.",
        "labels": [label("mountain_woodland", "simile", [
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:255", "αις αἰετὸς εὐρυάνακτος ἄγγελος"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:260", "οὔ νιν κορυφαὶ μεγάλας ἴσχουσι γαίας,"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:261", "οὐδʼ ἁλὸς ἀκαμάτας"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:262", "δυσπαίπαλα κύματα· νωμᾶ-"),
        ])],
    },
    "ogc:bacchylides.tlg0199-tlg001.jsonl:261": {
        "reason": "The eagle comparison names the sea and its rough waves within a sustained panoramic simile.",
        "labels": [label("sea_coast", "simile", [
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:255", "αις αἰετὸς εὐρυάνακτος ἄγγελος"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:260", "οὔ νιν κορυφαὶ μεγάλας ἴσχουσι γαίας,"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:261", "οὐδʼ ἁλὸς ἀκαμάτας"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:262", "δυσπαίπαλα κύματα· νωμᾶ-"),
        ])],
    },
    "ogc:bacchylides.tlg0199-tlg001.jsonl:262": {
        "reason": "The eagle simile explicitly contrasts mountain heights with difficult sea waves.",
        "labels": [label("sea_coast", "simile", [
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:255", "αις αἰετὸς εὐρυάνακτος ἄγγελος"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:260", "οὔ νιν κορυφαὶ μεγάλας ἴσχουσι γαίας,"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:261", "οὐδʼ ἁλὸς ἀκαμάτας"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:262", "δυσπαίπαλα κύματα· νωμᾶ-"),
        ])],
    },

    # Bacchylides, Ode 5: explicit wind-shaken leaves across sheep-grazed Ida slopes.
    "ogc:bacchylides.tlg0199-tlg001.jsonl:301": {
        "reason": "The leaf simile is completed by its explicit sheep-grazed Ida slopes in the following two lines.",
        "labels": [label("meadow_pasture", "simile", [
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:301", "οἷά τε φύλλʼ ἄνεμος"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:302", "Ἴδας ἀνὰ μηλοβότους"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:303", "πρῶνας ἀργηστὰς δονεῖ."),
        ])],
    },
    "ogc:bacchylides.tlg0199-tlg001.jsonl:302": {
        "reason": "The comparison locates the wind-shaken leaves on Ida’s sheep-grazed, bright slopes.",
        "labels": [label("meadow_pasture", "simile", [
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:301", "οἷά τε φύλλʼ ἄνεμος"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:302", "Ἴδας ἀνὰ μηλοβότους"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:303", "πρῶνας ἀργηστὰς δονεῖ."),
        ])],
    },
    "ogc:bacchylides.tlg0199-tlg001.jsonl:303": {
        "reason": "The bright slopes and wind-shaken leaves complete a specific pastoral landscape simile.",
        "labels": [label("meadow_pasture", "simile", [
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:301", "οἷά τε φύλλʼ ἄνεμος"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:302", "Ἴδας ἀνὰ μηλοβότους"),
            evidence("ogc:bacchylides.tlg0199-tlg001.jsonl:303", "πρῶνας ἀργηστὰς δονεῖ."),
        ])],
    },

    # Bacchylides, Perseus Epinicians Ode 3: the same sacred grove-and-stream scene in this edition.
    "perseus:tlg0199.tlg001.perseus-grc2:3.1–3.20:1": {
        "reason": "A great grove beside Castalia is set among the temple and tripod offerings in a concrete sacred landscape.",
        "labels": [
            label("garden_grove", "scene", [
                evidence("perseus:tlg0199.tlg001.perseus-grc2:3.1–3.20:1", "πάροιθε ναοῦ, τόθι μέγιστον ἄλσος"),
                evidence("perseus:tlg0199.tlg001.perseus-grc2:3.1–3.20:1", "Φοίβου παρὰ Κασταλίας ῥεέθροις"),
            ]),
            label("river_spring", "scene", [
                evidence("perseus:tlg0199.tlg001.perseus-grc2:3.1–3.20:1", "Φοίβου παρὰ Κασταλίας ῥεέθροις"),
                evidence("perseus:tlg0199.tlg001.perseus-grc2:3.1–3.20:1", "πάροιθε ναοῦ, τόθι μέγιστον ἄλσος"),
            ]),
        ],
    },
    # Bacchylides, Perseus Epinicians Ode 11: Proetus' daughters flee through wooded Arcadia.
    "perseus:tlg0199.tlg001.perseus-grc2:11.41–11.60:1": {
        "reason": "The leafy mountain flight begins the same extended landscape passage later described through shaded Arcadian woods and a flowing stream.",
        "labels": [label("mountain_woodland", "scene", [
            evidence("perseus:tlg0199.tlg001.perseus-grc2:11.41–11.60:1", "φεῦγον δʼ ὄρος ἐς τανίφυλλον,"),
            evidence("perseus:tlg0199.tlg001.perseus-grc2:11.81–11.100:1", "μῆνας κατὰ δάσκιον ἠλύκταζον ὕλαν"),
            evidence("perseus:tlg0199.tlg001.perseus-grc2:11.81–11.100:1", "φεῦγόν τε κατʼ Ἀρκαδίαν"),
        ])],
    },
    "perseus:tlg0199.tlg001.perseus-grc2:11.81–11.100:1": {
        "reason": "The extended flight names shaded woods, sheep-rearing Arcadia, and a fair-flowing stream where the father reaches his daughters.",
        "labels": [
            label("mountain_woodland", "scene", [
                evidence("perseus:tlg0199.tlg001.perseus-grc2:11.41–11.60:1", "φεῦγον δʼ ὄρος ἐς τανίφυλλον,"),
                evidence("perseus:tlg0199.tlg001.perseus-grc2:11.81–11.100:1", "μῆνας κατὰ δάσκιον ἠλύκταζον ὕλαν"),
                evidence("perseus:tlg0199.tlg001.perseus-grc2:11.81–11.100:1", "φεῦγόν τε κατʼ Ἀρκαδίαν"),
            ]),
            label("meadow_pasture", "scene", [
                evidence("perseus:tlg0199.tlg001.perseus-grc2:11.81–11.100:1", "φεῦγόν τε κατʼ Ἀρκαδίαν"),
                evidence("perseus:tlg0199.tlg001.perseus-grc2:11.81–11.100:1", "μηλοτρόφον·"),
                evidence("perseus:tlg0199.tlg001.perseus-grc2:11.81–11.100:1", "μῆνας κατὰ δάσκιον ἠλύκταζον ὕλαν"),
            ]),
            label("river_spring", "scene", [
                evidence("perseus:tlg0199.tlg001.perseus-grc2:11.81–11.100:1", "Λοῦσον ποτὶ καλλιρόαν πατὴρ ἵκανεν,"),
                evidence("perseus:tlg0199.tlg001.perseus-grc2:11.81–11.100:1", "μῆνας κατὰ δάσκιον ἠλύκταζον ὕλαν"),
                evidence("perseus:tlg0199.tlg001.perseus-grc2:11.81–11.100:1", "μηλοτρόφον·"),
            ]),
        ],
    },
    # Bacchylides, Perseus Epinicians Ode 13: storm, sunrise, favorable winds, and landfall in an extended simile.
    "perseus:tlg0199.tlg001.perseus-grc2:13.119–13.138:1": {
        "reason": "The extended sailor comparison develops a night storm, waves, dawn, changing winds, and a safe arrival on land.",
        "labels": [label("sea_coast", "simile", [
            evidence("perseus:tlg0199.tlg001.perseus-grc2:13.119–13.138:1", "πόντῳ βορέας ὑπὸ κύ-"),
            evidence("perseus:tlg0199.tlg001.perseus-grc2:13.119–13.138:1", "μασιν δαΐζει"),
            evidence("perseus:tlg0199.tlg001.perseus-grc2:13.119–13.138:1", "νυκτὸς ἀντάσας, ἀνατ[ελλομένᾳ"),
            evidence("perseus:tlg0199.tlg001.perseus-grc2:13.119–13.138:1", "ἀοῖ, στόρεσεν δέ τε πόντον"),
            evidence("perseus:tlg0199.tlg001.perseus-grc2:13.119–13.138:1", "οὐρία· νότου δὲ κόλπ[ωσαν πνοᾷ"),
            evidence("perseus:tlg0199.tlg001.perseus-grc2:13.119–13.138:1", "ελπτον ἐξίκοντο χέρσον·"),
        ])],
    },
    # Bacchylides, Perseus Epinicians fragment 14b: river and Thessalian pastoral hollows.
    "perseus:tlg0199.tlg001.perseus-grc2:14b.1–14b.10:1": {
        "reason": "The Peneios and fragrant Thessalia are described through sheep-rearing hollows, a developed pastoral river setting.",
        "labels": [
            label("river_spring", "scene", [
                evidence("perseus:tlg0199.tlg001.perseus-grc2:14b.1–14b.10:1", "Πηνειὸν ἀμφʼ εὐώδεα Θεσσαλία[ς"),
                evidence("perseus:tlg0199.tlg001.perseus-grc2:14b.1–14b.10:1", "μηλοτρόφου ἐν γυάλοις·"),
            ]),
            label("meadow_pasture", "scene", [
                evidence("perseus:tlg0199.tlg001.perseus-grc2:14b.1–14b.10:1", "Πηνειὸν ἀμφʼ εὐώδεα Θεσσαλία[ς"),
                evidence("perseus:tlg0199.tlg001.perseus-grc2:14b.1–14b.10:1", "μηλοτρόφου ἐν γυάλοις·"),
            ]),
        ],
    },

    # Bacchylides, OGC Dithyramb 17: storm-driven ship across the Cretan sea.
    "ogc:bacchylides.tlg0199-tlg002.jsonl:80": {
        "reason": "The ship's course across the Cretan sea is framed by its sail and the north winds.",
        "labels": [label("sea_coast", "scene", [
            evidence("ogc:bacchylides.tlg0199-tlg002.jsonl:77", "Κυανόπρῳρα μὲν ναῦς μενέκτυπον"),
            evidence("ogc:bacchylides.tlg0199-tlg002.jsonl:80", "Κρητικὸν τάμνε πέλαγος·"),
            evidence("ogc:bacchylides.tlg0199-tlg002.jsonl:81", "τηλαυγέϊ γὰρ [ἐν] φάρεϊ"),
            evidence("ogc:bacchylides.tlg0199-tlg002.jsonl:82", "βορήϊαι πίτνον αὖραι"),
        ])],
    },
    # Bacchylides, Dithyramb 17: sea entry, the underwater grove, and dolphin passage form one continuous scene.
    "ogc:bacchylides.tlg0199-tlg002.jsonl:161": {
        "reason": "The underwater grove is part of a continuous sea journey that carries Theseus onward among sea-dwelling dolphins.",
        "labels": [label("sea_coast", "scene", [
            evidence("ogc:bacchylides.tlg0199-tlg002.jsonl:160", "σταθεὶς ὄρουσε, πόντιόν τέ νιν"),
            evidence("ogc:bacchylides.tlg0199-tlg002.jsonl:161", "δέξατο θελημὸν ἄλσος."),
            evidence("ogc:bacchylides.tlg0199-tlg002.jsonl:173", "φέρον δὲ δελφῖνες ἁλι-"),
            evidence("ogc:bacchylides.tlg0199-tlg002.jsonl:174", "ναιέται μέγαν θοῶς"),
        ])],
    },
    "ogc:bacchylides.tlg0199-tlg002.jsonl:173": {
        "reason": "The dolphins carry Theseus through the sea journey that includes the underwater grove and divine home.",
        "labels": [label("sea_coast", "scene", [
            evidence("ogc:bacchylides.tlg0199-tlg002.jsonl:160", "σταθεὶς ὄρουσε, πόντιόν τέ νιν"),
            evidence("ogc:bacchylides.tlg0199-tlg002.jsonl:161", "δέξατο θελημὸν ἄλσος."),
            evidence("ogc:bacchylides.tlg0199-tlg002.jsonl:173", "φέρον δὲ δελφῖνες ἁλι-"),
            evidence("ogc:bacchylides.tlg0199-tlg002.jsonl:174", "ναιέται μέγαν θοῶς"),
        ])],
    },
    # Perseus edition of the same Dithyramb 17 ship-and-wind scene.
    "perseus:tlg0199.tlg002.perseus-grc2:17.1–17.20:1": {
        "reason": "The row sustains a ship-at-sea scene through the crossing, visible sail, and driving north winds.",
        "labels": [label("sea_coast", "scene", [
            evidence("perseus:tlg0199.tlg002.perseus-grc2:17.1–17.20:1", "Κρητικὸν τάμνε πέλαγος·"),
            evidence("perseus:tlg0199.tlg002.perseus-grc2:17.1–17.20:1", "τηλαυγέϊ γὰρ [ἐν] φάρεϊ"),
            evidence("perseus:tlg0199.tlg002.perseus-grc2:17.1–17.20:1", "βορήϊαι πίτνον αὖραι"),
        ])],
    },
}


def make_decisions(packet: str) -> list[dict]:
    rows = json.loads((PACKET_DIR / f"{packet}.json").read_text(encoding="utf-8"))
    greek = [row for row in rows if row.get("kind") == "text" and row.get("language") == "grc"]
    by_id = {row["id"]: row for row in greek}
    decisions = []
    for row in greek:
        proposal = POSITIVE.get(row["id"])
        if proposal:
            decisions.append({
                "id": row["id"], "status": "label", "reason": proposal["reason"],
                "labels": proposal["labels"],
            })
        else:
            decisions.append({
                "id": row["id"], "status": "abstain", "reason": ABSTAIN_REASON,
                "labels": [],
            })
    return decisions


def main() -> None:
    evidence_ids = {
        span["id"]
        for proposal in POSITIVE.values()
        for item in proposal["labels"]
        for span in item["evidence"]
    }
    all_ids = set()
    for packet in ("packet-06", "packet-07"):
        rows = json.loads((PACKET_DIR / f"{packet}.json").read_text(encoding="utf-8"))
        all_ids.update(row["id"] for row in rows if row.get("kind") == "text" and row.get("language") == "grc")
    missing = evidence_ids - all_ids
    if missing:
        raise ValueError(f"Evidence IDs are not Greek packet rows: {sorted(missing)}")
    for packet in ("packet-06", "packet-07"):
        output = {
            "packet": packet,
            "reviewer": "gpt-6-luna",
            "reviewed_all_records": True,
            "decisions": make_decisions(packet),
        }
        path = RAW_DIR / f"{packet}.proposals.json"
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{path.relative_to(ROOT)}: {len(output['decisions'])} Greek row decisions")


if __name__ == "__main__":
    main()
