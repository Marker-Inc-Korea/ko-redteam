"""간접 PI Tier-2 분류기(KcELECTRA) — scan_context 룰(recall 54%) 천장 돌파용.
train=생성 코퍼스(오염문서 공격=1 / 무해 RAG문서=0), held-out test=원본 indirect_pi_set(80, 룰이 54%만 잡던 것).
문서라 max_length=512. 출력=ko_indirect_pi_clf/final."""
import json, random
from pathlib import Path
import torch
from transformers import (AutoTokenizer, AutoModelForSequenceClassification,
                          TrainingArguments, Trainer, DataCollatorWithPadding)
from datasets import Dataset

from pathlib import Path as _P
R = _P(__file__).resolve().parent.parent / "tests" / "fixtures"
BASE = "beomi/KcELECTRA-base-v2022"
OUT = _P(__file__).resolve().parent / "ko_indirect_pi_clf"
random.seed(42); torch.manual_seed(42)

corp = json.load(open(R/"indirect_pi_trainset.json"))       # {attacks:[], benign:[]}
atk, ben = corp["attacks"], corp["benign"]
random.shuffle(ben)
# held-out benign 60, 나머지 학습
ben_test, ben_train = ben[:60], ben[60:]
test_atk = json.load(open(R/"indirect_pi_set.json"))["indirect_pi"]   # 원본 80 = 공격 테스트(룰 54%)

def rows(a, b): r=[{"text":x,"label":1} for x in a]+[{"text":x,"label":0} for x in b]; random.shuffle(r); return r
train_rows = rows(atk, ben_train)
n_val=max(60,len(train_rows)//10); val_rows, train_rows = train_rows[:n_val], train_rows[n_val:]
test_rows = rows(test_atk, ben_test)
print(f"train {len(train_rows)} / val {len(val_rows)} / test {len(test_rows)} (공격 {len(test_atk)}·무해 {len(ben_test)})")

tok = AutoTokenizer.from_pretrained(BASE)
ds = {k: Dataset.from_list(v).map(lambda b: tok(b["text"], truncation=True, max_length=512), batched=True)
      for k,v in [("train",train_rows),("val",val_rows),("test",test_rows)]}
mdl = AutoModelForSequenceClassification.from_pretrained(BASE, num_labels=2,
        id2label={0:"benign",1:"indirect_pi"}, label2id={"benign":0,"indirect_pi":1})

def metrics(p):
    pred=p.predictions.argmax(-1); y=p.label_ids
    tp=int(((pred==1)&(y==1)).sum()); fn=int(((pred==0)&(y==1)).sum())
    fp=int(((pred==1)&(y==0)).sum()); tn=int(((pred==0)&(y==0)).sum())
    rec=tp/(tp+fn+1e-9); fpr=fp/(fp+tn+1e-9); prec=tp/(tp+fp+1e-9)
    return {"acc":round((tp+tn)/len(y)*100,1),"recall":round(rec*100,1),"fpr":round(fpr*100,1),"f1":round(2*prec*rec/(prec+rec+1e-9)*100,1)}

args=TrainingArguments(output_dir=str(OUT/"ckpt"), num_train_epochs=5, per_device_train_batch_size=8,
        per_device_eval_batch_size=16, learning_rate=2e-5, weight_decay=0.01, warmup_ratio=0.1,
        eval_strategy="epoch", save_strategy="no", logging_steps=20, report_to=[], seed=42)
t=Trainer(mdl,args,train_dataset=ds["train"],eval_dataset=ds["val"],processing_class=tok,
          data_collator=DataCollatorWithPadding(tok),compute_metrics=metrics)
t.train()
print("VAL", t.evaluate(ds["val"]))
print("TEST(원본 indirect_pi 80·룰54% / 무해 held-out)", t.evaluate(ds["test"]))
t.save_model(str(OUT/"final")); tok.save_pretrained(str(OUT/"final"))
