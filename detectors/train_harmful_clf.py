"""유해출력 분류기(KcELECTRA) — output-guard 유해 카테고리(illegal/weapons/self_harm/unsafe_advice)
recall 보강용(룰 6~13%, judge 28~42%). positive=유해순응(topic-level), negative=안전답변+거부.
held-out=생성 20% + 실제 gemma 유해순응(참고). 출력=ko_harmful_clf/final."""
import json, random
from pathlib import Path
import torch
from transformers import (AutoTokenizer, AutoModelForSequenceClassification,
                          TrainingArguments, Trainer, DataCollatorWithPadding)
from datasets import Dataset

from pathlib import Path as _P
R = _P(__file__).resolve().parent.parent / "tests" / "fixtures"
BASE = "beomi/KcELECTRA-base-v2022"; OUT = _P(__file__).resolve().parent / "ko_harmful_clf"
random.seed(42); torch.manual_seed(42)

# NOTE: 원시 유해 positive 는 레포 미포함(gitignore) — 재현 시 생성 필요.
corp = json.load(open(R/"harmful_clf_train.json"))          # {harmful, safe}
harm, safe = corp["harmful"], corp["safe"]
# 실제 jailbreak 출력 스타일 positive 추가(일반화 개선용)
try:
    harm = harm + json.load(open(R/"harmful_realstyle.json"))["harmful_realstyle"]
except Exception:
    pass
# negative 보강: refusal 검증셋의 거부(거부=안전)
for f in ("ko_refusal_valset.json", "ko_refusal_valset2.json"):
    d = json.load(open(R/f)); safe += d["refusals"]
random.shuffle(harm); random.shuffle(safe)
# held-out: 유해 20% + 안전 20%
nh, ns = len(harm)//5, len(safe)//5
harm_te, harm_tr = harm[:nh], harm[nh:]
safe_te, safe_tr = safe[:ns], safe[ns:]

def rows(a, b): r=[{"text":x,"label":1} for x in a]+[{"text":x,"label":0} for x in b]; random.shuffle(r); return r
train_rows = rows(harm_tr, safe_tr)
n_val=max(60,len(train_rows)//10); val_rows, train_rows = train_rows[:n_val], train_rows[n_val:]
test_rows = rows(harm_te, safe_te)
print(f"train {len(train_rows)} / val {len(val_rows)} / test {len(test_rows)} (유해 {len(harm_te)}·안전 {len(safe_te)})")

tok = AutoTokenizer.from_pretrained(BASE)
ds = {k: Dataset.from_list(v).map(lambda b: tok(b["text"], truncation=True, max_length=256), batched=True)
      for k,v in [("train",train_rows),("val",val_rows),("test",test_rows)]}
mdl = AutoModelForSequenceClassification.from_pretrained(BASE, num_labels=2,
        id2label={0:"safe",1:"harmful"}, label2id={"safe":0,"harmful":1})

def metrics(p):
    pred=p.predictions.argmax(-1); y=p.label_ids
    tp=int(((pred==1)&(y==1)).sum()); fn=int(((pred==0)&(y==1)).sum())
    fp=int(((pred==1)&(y==0)).sum()); tn=int(((pred==0)&(y==0)).sum())
    rec=tp/(tp+fn+1e-9); fpr=fp/(fp+tn+1e-9); prec=tp/(tp+fp+1e-9)
    return {"acc":round((tp+tn)/len(y)*100,1),"recall":round(rec*100,1),"fpr":round(fpr*100,1),"f1":round(2*prec*rec/(prec+rec+1e-9)*100,1)}

args=TrainingArguments(output_dir=str(OUT/"ckpt"), num_train_epochs=5, per_device_train_batch_size=16,
        per_device_eval_batch_size=32, learning_rate=2e-5, weight_decay=0.01, warmup_ratio=0.1,
        eval_strategy="epoch", save_strategy="no", logging_steps=20, report_to=[], seed=42)
t=Trainer(mdl,args,train_dataset=ds["train"],eval_dataset=ds["val"],processing_class=tok,
          data_collator=DataCollatorWithPadding(tok),compute_metrics=metrics)
t.train()
print("VAL", t.evaluate(ds["val"]))
print("TEST(held-out)", t.evaluate(ds["test"]))
# 실제 gemma 유해순응(참고, 노이즈 有)
try:
    rg=json.load(open(R/"real_harmful_gemma.json"))["real_harmful"]
    rt=Dataset.from_list([{"text":x,"label":1} for x in rg]).map(lambda b: tok(b["text"],truncation=True,max_length=256),batched=True)
    print("실제 gemma 유해순응(참고)", t.evaluate(rt))
except Exception as e: print("real skip:", e)
t.save_model(str(OUT/"final")); tok.save_pretrained(str(OUT/"final"))
