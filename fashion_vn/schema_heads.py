"""Practical extension: explicit Vietnamese groups on top of the learned VSE.

These heads use a manually seeded schema, NOT the automatically discovered groups.
They avoid treating arbitrary noisy clusters as mutually exclusive attributes.
"""
import argparse
import json
from pathlib import Path
import torch
from torch.nn import functional as F
from .model import JointEmbedding, ConceptHead
from .prepare import read_rows, write_json
from .train import load_features
from .text import LEXICON, VISUAL_GROUPS

def schema():
    groups = {g: (g, list(values)) for g, values in LEXICON.items() if g != 'material_claim'}
    groups.pop('sleeve')
    groups['sleeve_length'] = ('sleeve', ['tay_dài', 'tay_ngắn', 'tay_lỡ', 'không_tay'])
    groups['sleeve_shape'] = ('sleeve', ['tay_phồng', 'tay_loe', 'tay_raglan'])
    groups['neckline'] = ('neckline', ['cổ_tròn', 'cổ_v', 'cổ_vuông', 'cổ_lọ', 'cổ_yếm', 'cổ_đổ', 'cổ_bẻ'])
    groups['shoulder_style'] = ('neckline', ['trễ_vai', 'hai_dây', 'một_vai'])
    return groups

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', default='outputs/prepared/manifest.jsonl')
    p.add_argument('--cache', default='outputs/cache_resnet18')
    p.add_argument('--models', default='models/local_resnet18')
    p.add_argument('--epochs', type=int, default=30)
    p.add_argument('--min-count', type=int, default=5)
    p.add_argument('--threads', type=int, default=4)
    p.add_argument('--seed', type=int, default=42)
    a = p.parse_args()
    torch.manual_seed(a.seed)
    torch.set_num_threads(a.threads)
    rows = read_rows(a.manifest)
    cache = Path(a.cache)
    meta = json.loads((cache/'metadata.json').read_text())
    summary = {}
    for path in sorted(Path(a.models).glob('*/vse.pt')):
        ck = torch.load(path, map_location='cpu', weights_only=True)
        if ck['cache_metadata'] != meta:
            raise ValueError('Cache does not match trained VSE.')
        cat = ck['category']
        rs = [r for r in rows if r['category'] == cat and r['image_status'] == 'ok'
              and r['split'] in ('train', 'val')
              and not any(f in r['flags'] for f in ('listing_multiple_variants', 'possible_negation_review'))]
        vse = JointEmbedding(ck['channels'], len(ck['vocab']), ck['dim'])
        vse.load_state_dict(ck['state_dict'])
        vse.eval()
        with torch.no_grad():
            Z = vse.image(load_features(rs, cache))
        states, heads = {}, []
        for name, (parent, values) in schema().items():
            if parent not in VISUAL_GROUPS.get(cat, set()):
                continue
            observations = [set(r['title_attributes'].get(parent, [])) & set(values) for r in rs]
            counts = {v: sum(r['split']=='train' and obs == {v} for r,obs in zip(rs,observations)) for v in values}
            attrs = [v for v in values if counts[v] >= a.min_count]
            if len(attrs) < 2:
                continue
            tx, ty, vx, vy = [], [], [], []
            for i, (r, obs) in enumerate(zip(rs, observations)):
                if len(obs) != 1 or next(iter(obs)) not in attrs:
                    continue
                indexes, targets = (tx, ty) if r['split']=='train' else (vx, vy)
                indexes.append(i)
                targets.append(attrs.index(next(iter(obs))))
            if len(tx) < 20:
                continue
            x, y = Z[tx], torch.tensor(ty)
            head = ConceptHead(ck['dim'], len(attrs))
            optimizer = torch.optim.AdamW(head.parameters(), lr=.003, weight_decay=1e-3)
            weights = torch.tensor([counts[v] for v in attrs]).float().rsqrt()
            weights /= weights.mean()
            best, stale, saved = float('inf'), 0, None
            for epoch in range(a.epochs):
                head.train()
                for ix in torch.randperm(len(x)).split(64):
                    loss = F.cross_entropy(head(x[ix]), y[ix], weight=weights)
                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()
                head.eval()
                if len(vx) >= 8:
                    with torch.no_grad():
                        vl = float(F.cross_entropy(head(Z[vx]), torch.tensor(vy)))
                    if vl < best:
                        best, stale = vl, 0
                        saved = {k: v.detach().clone() for k,v in head.state_dict().items()}
                    else:
                        stale += 1
                    if stale >= 5:
                        break
                elif epoch >= 9:
                    break  # fixed 10 epochs if weak validation is too small
            if saved is None:
                saved = head.state_dict()
            states[name] = saved
            heads.append(dict(concept_id=name, parent_group=parent, attributes=attrs,
                              train_examples=len(tx), val_examples=len(vx), counts=[counts[v] for v in attrs],
                              validation_source='title_weak_labels', calibrated=False,
                              schema_source='manual_vietnamese_seed_schema', epochs_run=epoch+1))
        torch.save({'heads': states, 'metadata': heads, 'dim': ck['dim'],
                    'method': 'manual_schema_extension_on_learned_vse'}, path.parent/'schema_heads.pt')
        write_json(path.parent/'schema_heads_metadata.json', heads)
        summary[cat] = len(heads)
        print(f'{cat}: trained {len(heads)} schema heads', flush=True)
    write_json(Path(a.models)/'schema_summary.json', summary)

if __name__ == '__main__':
    main()
