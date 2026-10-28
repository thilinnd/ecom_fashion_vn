"""Evaluate joint/semantic/spatial cluster ablations against manually grouped words."""
import argparse
import csv
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import normalize
from sklearn.metrics import homogeneity_completeness_v_measure
from .prepare import write_json

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--representations', required=True, help='attribute_representations.npz from one category')
    p.add_argument('--gold', required=True, help='CSV with attribute and concept_gold; manually reviewed')
    p.add_argument('--out', default='outputs/cluster_evaluation.json')
    p.add_argument('--seed', type=int, default=42)
    a = p.parse_args()
    data = np.load(a.representations, allow_pickle=False)
    vocab = data['vocab'].tolist()
    with open(a.gold, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    gold = {r['attribute']: r['concept_gold'].strip() for r in rows if r['concept_gold'].strip()}
    if len(gold) != sum(bool(r['concept_gold'].strip()) for r in rows):
        raise ValueError('Duplicate gold attributes; adjudicate before evaluating.')
    ids = [i for i, t in enumerate(vocab) if t in gold]
    if len(ids) < 2:
        raise ValueError('Need at least two manually grouped words present in model vocabulary.')
    target = [gold[vocab[i]] for i in ids]
    k = len(set(data['clusters'].tolist()))
    results = {}
    # Fit using all training-derived attribute representations, never gold labels.
    variants = {'joint': data['clusters'],
                'semantic_only': KMeans(n_clusters=k, n_init=10, random_state=a.seed).fit_predict(normalize(data['semantic'])),
                'spatial_only': KMeans(n_clusters=k, n_init=10, random_state=a.seed).fit_predict(normalize(data['spatial']))}
    for name, cluster in variants.items():
        h, c, v = homogeneity_completeness_v_measure(target, cluster[ids])
        results[name] = dict(homogeneity=h, completeness=c, v_measure=v)
    from pathlib import Path
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    write_json(a.out, dict(n_gold=len(gold), n_evaluated=len(ids), n_clusters=k, metrics=results))
    print(results)

if __name__ == '__main__':
    main()
