"""Evaluate manually annotated gold, excluding unknowns; never use titles as gold."""
import argparse
import collections
import csv
import json
from pathlib import Path
from .prepare import write_json

def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def metrics(items):
    tp = sum(y == 1 and p == 1 for y, p in items)
    fp = sum(y == 0 and p == 1 for y, p in items)
    fn = sum(y == 1 and p == 0 for y, p in items)
    tn = sum(y == 0 and p == 0 for y, p in items)
    precision = tp / (tp+fp) if tp+fp else None
    recall = tp / (tp+fn) if tp+fn else None
    f1 = 2*tp / (2*tp+fp+fn) if 2*tp+fp+fn else None
    return dict(n=len(items), tp=tp, fp=fp, fn=fn, tn=tn, precision=precision, recall=recall, f1=f1)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gold', required=True, help='CSV: product_id,split,concept,attribute,label,annotator')
    p.add_argument('--scores', default='outputs/predictions/image_scores.csv')
    p.add_argument('--split', choices=['val', 'test'], default='test')
    p.add_argument('--threshold', type=float, help='Use score threshold instead of exported selection')
    p.add_argument('--out', default='outputs/evaluation.json')
    a = p.parse_args()
    if a.threshold is not None and not 0 <= a.threshold <= 1:
        p.error('threshold must lie in [0,1]')
    gold = [r for r in read_csv(a.gold) if r['split'] == a.split]
    if not gold:
        raise ValueError('No gold rows for requested split. Manually annotate first.')
    scores = {}
    for r in read_csv(a.scores):
        if r['split'] != a.split:
            continue
        key = (r['product_id'], r['attribute'])
        if key in scores:
            raise ValueError(f'Duplicate image score: {key}')
        scores[key] = r
    seen, items, grouped = set(), [], collections.defaultdict(list)
    unknown, missing = 0, 0
    for r in gold:
        key = (r['product_id'], r['attribute'])
        if key in seen:
            raise ValueError(f'Duplicate gold {key}; adjudicate annotators before evaluation.')
        seen.add(key)
        label = r['label'].strip().lower()
        if label in {'unknown', 'not_visible', 'not_applicable'}:
            unknown += 1
            continue
        if label not in {'present', 'absent', '1', '0'}:
            raise ValueError(f'Invalid/unfilled gold label {label!r}; explicitly mark unknown if needed.')
        y = int(label in {'present', '1'})
        score = scores.get(key)
        if score is None:
            missing += 1
            pred = 0  # abstention counts as FN for a gold positive
        else:
            pred = int(float(score['score']) >= a.threshold) if a.threshold is not None else int(score['selected'])
        pair = (y, pred)
        items.append(pair)
        grouped[r['attribute']].append(pair)
    if not items:
        raise ValueError('No observable gold labels to evaluate.')
    per_attribute = {k: metrics(v) for k, v in grouped.items()}
    valid_f1 = [v['f1'] for v in per_attribute.values() if v['f1'] is not None]
    result = dict(split=a.split, micro=metrics(items),
                  macro_f1=sum(valid_f1)/len(valid_f1) if valid_f1 else None,
                  per_attribute=per_attribute, excluded_unknown=unknown,
                  missing_prediction_pairs=missing, scored_pair_coverage=(len(items)-missing)/len(items),
                  note='Evaluation applies only to explicitly annotated pairs; missing positives count as false negatives.')
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    write_json(a.out, result)
    print(json.dumps(result, ensure_ascii=True, indent=2))

if __name__ == '__main__':
    main()
