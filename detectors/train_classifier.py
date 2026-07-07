"""ko 거부 학습 분류기 — garak-ModernBERT(영어)의 한국어판(KcELECTRA).

레포 fixture(../tests/fixtures)로 학습·평가. GPU 권장(SLURM). 결과 CLASSIFIER_FINDINGS.md 참조.
    python train_classifier.py            # → ./ko_refusal_clf/final (gitignore)
"""
from __future__ import annotations
import json, random
from pathlib import Path
import torch
from transformers import (AutoTokenizer, AutoModelForSequenceClassification,
                          TrainingArguments, Trainer, DataCollatorWithPadding)
from datasets import Dataset

HERE = Path(__file__).resolve().parent
FIX = HERE.parent / "tests" / "fixtures"
BASE = "beomi/KcELECTRA-base-v2022"
OUT = HERE / "ko_refusal_clf"
random.seed(42); torch.manual_seed(42)

tr = json.loads((FIX / "refusal_trainset.json").read_text())
te = json.loads((FIX / "refusal_valset2.json").read_text())   # held-out test
def rows(refs, nons): return [{"text": x, "label": 1} for x in refs] + [{"text": x, "label": 0} for x in nons]
train_rows = rows(tr["refusals"], tr["non_refusals"]); random.shuffle(train_rows)
n_val = max(60, len(train_rows)//10); val_rows, train_rows = train_rows[:n_val], train_rows[n_val:]
test_rows = rows(te["refusals"], te["compliances"] + te["benign_absence"])
print(f"train {len(train_rows)} / val {len(val_rows)} / test(held-out) {len(test_rows)}")

tok = AutoTokenizer.from_pretrained(BASE)
ds = {k: Dataset.from_list(v).map(lambda b: tok(b["text"], truncation=True, max_length=256), batched=True)
      for k, v in [("train", train_rows), ("val", val_rows), ("test", test_rows)]}
mdl = AutoModelForSequenceClassification.from_pretrained(
    BASE, num_labels=2, id2label={0: "non-refusal", 1: "refusal"}, label2id={"non-refusal": 0, "refusal": 1})

def metrics(p):
    pred = p.predictions.argmax(-1); y = p.label_ids
    tp = int(((pred == 1) & (y == 1)).sum()); fn = int(((pred == 0) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    rec = tp/(tp+fn+1e-9); fpr = fp/(fp+tn+1e-9); prec = tp/(tp+fp+1e-9)
    return {"acc": round((tp+tn)/len(y)*100, 1), "recall": round(rec*100, 1),
            "fpr": round(fpr*100, 1), "f1": round(2*prec*rec/(prec+rec+1e-9)*100, 1)}

args = TrainingArguments(output_dir=str(OUT/"ckpt"), num_train_epochs=5, per_device_train_batch_size=16,
        per_device_eval_batch_size=32, learning_rate=2e-5, weight_decay=0.01, warmup_ratio=0.1,
        eval_strategy="epoch", save_strategy="no", logging_steps=20, report_to=[], seed=42)
t = Trainer(mdl, args, train_dataset=ds["train"], eval_dataset=ds["val"],
            processing_class=tok, data_collator=DataCollatorWithPadding(tok), compute_metrics=metrics)
t.train()
print("VAL", t.evaluate(ds["val"]))
print("TEST(held-out valset2)", t.evaluate(ds["test"]))
t.save_model(str(OUT/"final")); tok.save_pretrained(str(OUT/"final"))
