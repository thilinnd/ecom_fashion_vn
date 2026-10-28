"""Export image-only hypotheses separately from title claims, with abstention."""
import argparse
import collections
import json
from pathlib import Path
import numpy as np
import openpyxl
import torch
from .model import JointEmbedding, ConceptHead
from .prepare import read_rows, write_json
from .text import LEXICON, VISUAL_GROUPS

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', default='outputs/prepared/manifest.jsonl')
    p.add_argument('--cache', default='outputs/cache_resnet18')
    p.add_argument('--models', default='models/local_resnet18')
    p.add_argument('--out', default='outputs/predictions')
    p.add_argument('--threshold', type=float, default=.7, help='Heuristic, not calibrated confidence')
    p.add_argument('--margin', type=float, default=.15)
    p.add_argument('--threads', type=int, default=4)
    p.add_argument('--head-type', choices=['discovered', 'schema'], default='discovered')
    p.add_argument('--categories', nargs='+', help='Optional category subset for targeted inference')
    a = p.parse_args()
    if not 0 <= a.threshold <= 1 or not 0 <= a.margin <= 1:
        p.error('threshold and margin must lie in [0,1]')
    torch.set_num_threads(a.threads)
    out, cache = Path(a.out), Path(a.cache)
    out.mkdir(parents=True, exist_ok=True)
    cache_meta = json.loads((cache / 'metadata.json').read_text())
    known = {v: c for c, values in LEXICON.items() for v in values}
    models = {}
    for path in Path(a.models).glob('*/vse.pt'):
        ck = torch.load(path, map_location='cpu', weights_only=True)
        if a.categories and ck['category'] not in set(a.categories):
            continue
        if ck['cache_metadata'] != cache_meta:
            raise ValueError(f'Backbone/cache mismatch: {path}')
        model = JointEmbedding(ck['channels'], len(ck['vocab']), ck['dim'])
        model.load_state_dict(ck['state_dict'])
        model.eval()
        head_file = 'heads.pt' if a.head_type == 'discovered' else 'schema_heads.pt'
        if not (path.parent/head_file).exists():
            raise ValueError(f'Missing {head_file} for {ck["category"]}; train requested heads first.')
        heads_ck = torch.load(path.parent / head_file, map_location='cpu', weights_only=True)
        heads = []
        for h in heads_ck['metadata']:
            net = ConceptHead(ck['dim'], len(h['attributes']))
            net.load_state_dict(heads_ck['heads'][str(h['concept_id'])])
            net.eval()
            heads.append((h, net))
        models[ck['category']] = (model, heads)
    if not models:
        raise ValueError('No trained models. Run train first.')
    rows = read_rows(a.manifest)
    if a.categories:
        requested = set(a.categories)
        rows = [row for row in rows if row['category'] in requested]
    book = openpyxl.Workbook(write_only=True)
    sheet = book.create_sheet('attributes')
    title_groups = list(LEXICON)
    image_groups = [g for g in LEXICON if g != 'material_claim']
    sheet.append(['product_id', 'title_raw', 'category_hint', 'split', 'image_path', 'image_status', 'prediction_status',
                  'title_attributes_json', 'image_candidates_json', 'review_required', 'flags'] +
                 ['title_' + g for g in title_groups] + ['image_' + g + '_candidates' for g in image_groups])
    status_counts, with_candidates = collections.Counter(), 0
    # Long scores include every head attribute, enabling unbiased evaluation on
    # pre-specified gold positives AND negatives, not just emitted predictions.
    import csv
    with (out / 'products.jsonl').open('w', encoding='utf-8') as f, \
            (out / 'image_scores.csv').open('w', encoding='utf-8-sig', newline='') as sf:
        writer = csv.DictWriter(sf, fieldnames=['product_id', 'split', 'category', 'concept', 'attribute',
                                               'score', 'selected', 'source'])
        writer.writeheader()
        with torch.inference_mode():
            for r in rows:
                cat = r['category']
                candidates, raw = [], []
                flags = list(r['flags'])
                status = 'predicted_unvalidated'
                path = cache / (r['image_sha256'] + '.npy')
                if r['image_status'] != 'ok':
                    status = 'missing_or_invalid_image'
                elif cat not in models:
                    status = 'no_category_model'
                elif not path.exists():
                    status = 'missing_image_features'
                else:
                    model, heads = models[cat]
                    feat = np.load(path).astype(np.float32).mean((1, 2))
                    z = model.image(torch.from_numpy(feat).unsqueeze(0))
                    for meta, head in heads:
                        probs = head(z).softmax(-1)[0].numpy()
                        best = int(probs.argmax())
                        second = float(np.partition(probs, -2)[-2])
                        accept = bool(probs[best] >= a.threshold and probs[best] - second >= a.margin)
                        name = meta['attributes'][best]
                        group = known.get(name, 'unmapped')
                        # Material composition cannot be established from a picture.
                        proposed = accept and group in VISUAL_GROUPS.get(cat, set())
                        item = dict(concept_id=meta['concept_id'], attribute=name,
                                    seed_group_hint=group, score=float(probs[best]),
                                    runner_up_margin=float(probs[best] - second),
                                    threshold_passed=accept, concept_reviewed=False,
                                    source='image_model_' + a.head_type, calibrated=False,
                                    grouping_source=('automatic_spatial_semantic_clusters' if a.head_type == 'discovered'
                                                     else 'manual_vietnamese_seed_schema'))
                        raw.append(item)
                        if proposed:
                            candidates.append(item)
                        for j, name_j in enumerate(meta['attributes']):
                            writer.writerow(dict(product_id=r['product_id'], split=r['split'], category=cat,
                                                 concept=f'{cat}:{meta["concept_id"]}', attribute=name_j,
                                                 score=float(probs[j]), selected=int(j == best and proposed),
                                                 source='image_model_' + a.head_type + '_uncalibrated'))
                    if not candidates:
                        status = 'abstained_no_standard_attribute' if heads else 'no_trained_attribute_heads'
                    proposed_groups = collections.defaultdict(set)
                    for item in candidates:
                        proposed_groups[item['seed_group_hint']].add(item['attribute'])
                    # Different discovered clusters may propose incompatible values
                    # of the same human-named group. Retain evidence, flag review.
                    for group, values in proposed_groups.items():
                        if len(values) > 1:
                            flags.append('multiple_image_candidates:' + group)
                        mentioned = set(r['title_attributes'].get(group, []))
                        if mentioned and values.isdisjoint(mentioned):
                            flags.append('image_title_disagreement:' + group)
                record = dict(product_id=r['product_id'], title_raw=r['title_raw'],
                              category_hint=cat, split=r['split'], image_path=r['image_path'],
                              image_status=r['image_status'], prediction_status=status,
                              title_attributes=r['title_attributes'], title_evidence=r['title_evidence'],
                              image_candidates=candidates, raw_concept_predictions=raw,
                              review_required=True, flags=flags)
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
                values = [r['product_id'], r['title_raw'], cat, r['split'], r['image_path'], r['image_status'], status,
                          json.dumps(r['title_attributes'], ensure_ascii=False),
                          json.dumps(candidates, ensure_ascii=False), True, ';'.join(flags)]
                values += [';'.join(r['title_attributes'].get(g, [])) for g in title_groups]
                values += [';'.join(c['attribute'] for c in candidates if c['seed_group_hint'] == g)
                           for g in image_groups]
                cells = []
                for value in values:
                    cell = openpyxl.cell.WriteOnlyCell(sheet, value=value)
                    if isinstance(value, str):
                        cell.data_type = 's'
                    cells.append(cell)
                sheet.append(cells)
                status_counts[status] += 1
                with_candidates += bool(candidates)
    book.save(out / 'fashion_vn_attributes.xlsx')
    summary = dict(n_products=len(rows), products_with_image_candidates=with_candidates,
                   status_counts=dict(status_counts), threshold=a.threshold, margin=a.margin,
                   calibrated=False, gold_evaluation_performed=False, head_type=a.head_type,
                   note='All image outputs are hypotheses requiring review; titles are weak seller claims.')
    write_json(out / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=True, indent=2))

if __name__ == '__main__':
    main()
