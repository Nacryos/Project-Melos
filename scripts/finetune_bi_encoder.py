"""Fine-tune the passage encoder on the Melos English-to-Greek pairs (GPU job).

Not run on the box: it needs a GPU and the training set from
scripts/build_training_pairs.py. Trains BAAI/bge-m3 (or any
sentence-transformers model) with MultipleNegativesRankingLoss, using the
listed hard negatives in addition to in-batch negatives, and reports Recall@k
on the dev split before and after.

  python scripts/finetune_bi_encoder.py --data data/training/melos-bi-encoder-pairs-2026-10-09 \
      --base BAAI/bge-m3 --out models/melos-bge-m3-ft-2026-10 --epochs 2 --batch 32

Requires: sentence-transformers>=3, datasets, torch with CUDA.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def triplets(rows: list[dict], negatives_per_pair: int) -> dict[str, list[str]]:
    """Explode each pair into (anchor, positive, negative) rows; pairs without negatives use the positive only."""
    anchors, positives, negatives = [], [], []
    for row in rows:
        negs = [n["text"] for n in row.get("negatives", [])][:negatives_per_pair]
        if not negs:
            anchors.append(row["anchor"]); positives.append(row["positive"]); negatives.append("")
            continue
        for neg in negs:
            anchors.append(row["anchor"]); positives.append(row["positive"]); negatives.append(neg)
    return {"anchor": anchors, "positive": positives, "negative": negatives}


def dev_evaluator(rows: list[dict], name: str):
    from sentence_transformers.evaluation import InformationRetrievalEvaluator
    queries, corpus, relevant = {}, {}, {}
    for index, row in enumerate(rows):
        qid = f"q{index}"
        queries[qid] = row["anchor"]
        corpus[row["positive_id"]] = row["positive"]
        relevant[qid] = {row["positive_id"]}
        for neg in row.get("negatives", []):
            corpus.setdefault(neg["id"], neg["text"])
    return InformationRetrievalEvaluator(queries, corpus, relevant, name=name, accuracy_at_k=[1, 5, 10],
                                         precision_recall_at_k=[1, 5, 10], mrr_at_k=[10], show_progress_bar=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--base", default="BAAI/bge-m3")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--epochs", type=float, default=2)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--negatives-per-pair", type=int, default=2)
    parser.add_argument("--languages", nargs="*", default=["eng"], help="anchor languages to train on (eng, ell)")
    args = parser.parse_args()

    import torch
    from datasets import Dataset
    from sentence_transformers import SentenceTransformer, SentenceTransformerTrainer, SentenceTransformerTrainingArguments
    from sentence_transformers.losses import MultipleNegativesRankingLoss

    if not torch.cuda.is_available():
        raise SystemExit("This job needs a GPU; the box only prepares data.")
    train_rows = [r for r in load_rows(args.data / "train.jsonl") if r["anchor_language"] in args.languages]
    dev_rows = [r for r in load_rows(args.data / "dev.jsonl") if r["anchor_language"] in args.languages]
    model = SentenceTransformer(args.base, device="cuda")
    model.max_seq_length = args.max_length
    evaluator = dev_evaluator(dev_rows, "melos-dev")
    before = evaluator(model)
    print("before:", {k: round(v, 4) for k, v in before.items() if "recall" in k or "mrr" in k})
    columns = triplets(train_rows, args.negatives_per_pair)
    # Rows without a negative get the positive as a harmless placeholder so the
    # loss still sees in-batch negatives.
    columns["negative"] = [neg or pos for neg, pos in zip(columns["negative"], columns["positive"])]
    dataset = Dataset.from_dict(columns).shuffle(seed=20261009)
    loss = MultipleNegativesRankingLoss(model)
    training = SentenceTransformerTrainingArguments(
        output_dir=str(args.out), num_train_epochs=args.epochs, per_device_train_batch_size=args.batch,
        learning_rate=args.lr, warmup_ratio=0.1, bf16=torch.cuda.is_bf16_supported(), fp16=not torch.cuda.is_bf16_supported(),
        batch_sampler="no_duplicates", eval_strategy="epoch", save_strategy="epoch", logging_steps=50, seed=20261009,
        report_to=[])
    trainer = SentenceTransformerTrainer(model=model, args=training, train_dataset=dataset, loss=loss, evaluator=evaluator)
    trainer.train()
    after = evaluator(model)
    print("after:", {k: round(v, 4) for k, v in after.items() if "recall" in k or "mrr" in k})
    model.save(str(args.out / "final"))
    (args.out / "eval.json").write_text(json.dumps({"before": before, "after": after, "train_rows": len(train_rows), "dev_rows": len(dev_rows),
                                                   "base": args.base, "epochs": args.epochs, "batch": args.batch, "lr": args.lr}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
