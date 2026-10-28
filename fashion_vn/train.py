"""Train frozen-CNN VSE, spatial+Word2vec concepts, and concept classifiers.

This runnable small-data baseline implements the paper's central mechanism, but
does not claim to reproduce its end-to-end fine-tuning or its reported accuracy.
"""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
import random
import numpy as np
import torch
from torch.nn import functional as F
from gensim.models import Word2Vec
from sklearn.cluster import KMeans
from sklearn.preprocessing import normalize
from .model import JointEmbedding, ConceptHead, ranking_loss
from .prepare import read_rows, write_json, write_csv
from .text import LEXICON

def bow_tensor(rows, vocab):
    lookup = {t: i for i, t in enumerate(vocab)}
    result = torch.zeros(len(rows), len(vocab))
    for i, r in enumerate(rows):
        for t in r['tokens']:
            if t in lookup:
                result[i, lookup[t]] += 1
    return result

def load_features(rows, cache):
    return torch.from_numpy(np.stack([
        np.load(cache / (r['image_sha256'] + '.npy')).astype(np.float32).mean((1, 2)) for r in rows]))

def train_category(category, all_rows, a, meta, allowed):
    out = Path(a.out) / category
    out.mkdir(parents=True, exist_ok=True)
    eligible = [r for r in all_rows if r['category'] == category and r['image_status'] == 'ok'
                and not any(f in r['flags'] for f in ('listing_multiple_variants', 'possible_negation_review'))]
    train = [r for r in eligible if r['split'] == 'train']
    val = [r for r in eligible if r['split'] == 'val']
    df = collections.Counter(t for r in train for t in set(r['tokens']))
    vocab = sorted(t for t, n in df.items() if n >= a.min_df and (allowed is None or t in allowed))
    vocab_set = set(vocab)
    train = [r for r in train if vocab_set.intersection(r['tokens'])]
    val = [r for r in val if vocab_set.intersection(r['tokens'])]
    if len(train) < a.min_products or len(val) < 2 or len(vocab) < 4:
        status = dict(status='skipped_insufficient_data', train=len(train), val=len(val), vocab=len(vocab))
        write_json(out / 'status.json', status)
        print(category, status, flush=True)
        return status
    cache = Path(a.cache)
    missing = [r for r in train + val if not (cache / (r['image_sha256'] + '.npy')).exists()]
    if missing:
        raise ValueError(f'{category}: {len(missing)} feature maps missing; run cache first.')
    X, Xv = load_features(train, cache), load_features(val, cache)
    B, Bv = bow_tensor(train, vocab), bow_tensor(val, vocab)
    group_ids = {g: i for i, g in enumerate(sorted({r['group_id'] for r in train + val}))}
    G = torch.tensor([group_ids[r['group_id']] for r in train])
    Gv = torch.tensor([group_ids[r['group_id']] for r in val])
    model = JointEmbedding(X.shape[1], len(vocab), a.dim)
    if a.initial_vse:
        ck = torch.load(a.initial_vse, map_location='cpu', weights_only=True)
        if ck['vocab'] != vocab or ck['category'] != category or ck['dim'] != a.dim:
            raise ValueError('Initial checkpoint category/vocabulary/dimension differs.')
        model.load_state_dict(ck['state_dict'])
    optimizer = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    history, best, stale = [], float('inf'), 0
    for epoch in range(a.epochs):
        model.train()
        order = torch.randperm(len(train))
        losses = []
        for idx in order.split(a.batch_size):
            if len(idx) < 2:
                continue
            loss = ranking_loss(model.image(X[idx]), model.text(B[idx]), G[idx], B[idx])
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
            optimizer.step()
            losses.append(loss.item())
        model.eval()
        with torch.no_grad():
            vl = [ranking_loss(model.image(Xv[idx]), model.text(Bv[idx]), Gv[idx], Bv[idx]).item()
                  for idx in torch.arange(len(val)).split(a.batch_size) if len(idx) > 1]
        validation = float(np.mean(vl))
        history.append(dict(epoch=epoch+1, train_loss=float(np.mean(losses)), val_weak_ranking_loss=validation))
        if validation < best:
            best, stale = validation, 0
            torch.save({'state_dict': model.state_dict(), 'vocab': vocab, 'dim': a.dim,
                        'channels': X.shape[1], 'category': category, 'cache_metadata': meta,
                        'seed': a.seed, 'method': 'frozen_backbone_spatial_vse_v1' if meta['frozen']
                        else 'finetuned_backbone_spatial_vse_v1'}, out / 'vse.pt')
        else:
            stale += 1
        if (epoch+1) % 5 == 0 or epoch == 0:
            print(f'{category}: epoch {epoch+1}, train {history[-1]["train_loss"]:.4f}, val {validation:.4f}', flush=True)
        if stale >= a.patience:
            break
    model.load_state_dict(torch.load(out / 'vse.pt', weights_only=True)['state_dict'])
    model.eval()
    write_json(out / 'training_history.json', history)
    # Semantic representation fitted ONLY on this category's training descriptions.
    sentences = [[t for t in r['tokens'] if t in vocab_set] for r in train]
    semantic = Word2Vec(sentences=sentences, vector_size=64, window=5, min_count=1,
                        sg=1, workers=1, seed=a.seed, epochs=50)
    semantic.save(str(out / 'word2vec.model'))
    E = np.stack([semantic.wv[t] for t in vocab])
    # EAAM(a,i,j) = word[a]^T W_image feature_map(i,j), averaged on positives.
    with torch.no_grad():
        word = F.normalize(model.word_embedding.weight, dim=1)
        effective = (word @ model.image_projection.weight).numpy()
    grid = 8 if meta['backbone'] == 'inception_v3' else 7
    A = np.zeros((len(vocab), grid * grid), dtype=np.float64)
    counts = np.zeros(len(vocab), dtype=np.int64)
    lookup = {t: i for i, t in enumerate(vocab)}
    for r in train:
        ids = sorted({lookup[t] for t in r['tokens'] if t in lookup})
        fmap = np.load(cache / (r['image_sha256'] + '.npy')).astype(np.float32).reshape(X.shape[1], -1)
        # Scale removes irrelevant variation in magnitude between product images.
        denom = float(np.linalg.norm(model.image_projection.weight.detach().numpy() @ fmap.mean(1)))
        A[ids] += effective[ids] @ fmap / max(denom, 1e-8)
        counts[ids] += 1
    A /= np.maximum(counts[:, None], 1)
    # Same dimension for semantics/spatial features in Inception configuration;
    # ResNet baseline has 49 spatial dimensions and 64 semantic dimensions.
    joint = np.concatenate([normalize(A), normalize(E)], axis=1)
    k = min(a.clusters, max(2, len(vocab)//4))
    labels = KMeans(n_clusters=k, random_state=a.seed, n_init=10).fit_predict(joint)
    np.savez_compressed(out / 'attribute_representations.npz', spatial=A, semantic=E,
                        counts=counts, vocab=np.asarray(vocab), clusters=labels)
    known = {v: c for c, values in LEXICON.items() for v in values}
    concepts, review = [], []
    for c in range(k):
        ids = np.where(labels == c)[0].tolist()
        concepts.append({'concept_id': c, 'attributes': [vocab[i] for i in ids], 'reviewed': False})
        for i in ids:
            review.append({'concept_id': c, 'attribute': vocab[i], 'train_df': int(counts[i]),
                           'seed_group_hint': known.get(vocab[i], ''), 'concept_name_reviewed': '',
                           'keep': '', 'notes': ''})
    write_json(out / 'concepts.json', concepts)
    write_csv(out / 'concept_review.csv', review, list(review[0]))
    # Train a subspace per discovered cluster. Missing labels stay unobserved;
    # no invented none-of-above labels. Multi-mention rows are excluded.
    with torch.no_grad():
        Z = model.image(X)
    states, head_meta = {}, []
    for concept in concepts:
        ids = [lookup[t] for t in concept['attributes']]
        positive = B[:, ids] > 0
        observed = positive.sum(1) == 1
        if len(ids) < 2 or observed.sum() < a.min_head_examples:
            continue
        z, target = Z[observed], positive[observed].int().argmax(1)
        frequencies = torch.bincount(target, minlength=len(ids))
        if (frequencies > 0).sum() < 2:
            continue
        head = ConceptHead(a.dim, len(ids))
        opt = torch.optim.AdamW(head.parameters(), lr=.003)
        weights = frequencies.clamp_min(1).float().rsqrt()
        weights /= weights.mean()
        for _ in range(a.head_epochs):
            for ix in torch.randperm(len(z)).split(a.batch_size):
                loss = F.cross_entropy(head(z[ix]), target[ix], weight=weights)
                opt.zero_grad()
                loss.backward()
                opt.step()
        states[str(concept['concept_id'])] = head.state_dict()
        head_meta.append(dict(concept_id=concept['concept_id'], attributes=concept['attributes'],
                              train_examples=int(observed.sum()), counts=frequencies.tolist()))
    torch.save({'heads': states, 'metadata': head_meta, 'dim': a.dim}, out / 'heads.pt')
    status = dict(status='trained_unvalidated', category=category, train=len(train), val=len(val),
                  vocabulary=len(vocab), concepts=k, heads=len(head_meta),
                  best_val_weak_ranking_loss=best, epochs_run=len(history),
                  configuration=vars(a), cache_metadata=meta,
                  manifest_sha256=hashlib.sha256(Path(a.manifest).read_bytes()).hexdigest(),
                  limitations=[('Frozen ImageNet CNN, not paper end-to-end fine-tuning.' if meta['frozen']
                                else 'CNN fine-tuned separately, followed by concept discovery.'),
                               'No clothing detector/crops; full-image letterboxing.',
                               'Concept heads assume alternatives within an unreviewed cluster.',
                               'Softmax scores are uncalibrated; missing concepts require abstention.',
                               'No gold label quality evaluation has been performed.'])
    write_json(out / 'status.json', status)
    return status

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', default='outputs/prepared/manifest.jsonl')
    p.add_argument('--cache', default='outputs/cache_resnet18')
    p.add_argument('--out', default='models/local_resnet18')
    p.add_argument(
        '--categories', nargs='+',
        default=['top', 'dress', 'pants', 'skirt', 'jacket', 'bag', 'hat', 'set', 'shoe'],
    )
    p.add_argument('--vocabulary-review', help='Optional edited CSV with token/include columns')
    p.add_argument('--initial-vse', help='Optional warm start after category CNN fine-tuning')
    p.add_argument('--min-df', type=int, default=5)
    p.add_argument('--min-products', type=int, default=50)
    p.add_argument('--min-head-examples', type=int, default=20)
    p.add_argument('--dim', type=int, default=512)
    p.add_argument('--clusters', type=int, default=30)
    p.add_argument('--epochs', type=int, default=30)
    p.add_argument('--head-epochs', type=int, default=10)
    p.add_argument('--patience', type=int, default=5)
    p.add_argument('--batch-size', type=int, default=64)
    p.add_argument('--lr', type=float, default=.001)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--threads', type=int, default=4)
    a = p.parse_args()
    if min(a.epochs, a.head_epochs, a.dim, a.min_df, a.threads) < 1 or a.batch_size < 2:
        p.error('epochs, dimensions, min-df and threads must be positive; batch-size >= 2')
    random.seed(a.seed)
    np.random.seed(a.seed)
    torch.manual_seed(a.seed)
    torch.set_num_threads(a.threads)
    rows = read_rows(a.manifest)
    meta = json.loads((Path(a.cache) / 'metadata.json').read_text())
    if not meta['frozen'] and a.categories != [meta['category']]:
        raise ValueError('Fine-tuned cache must be used only with its own category.')
    allowed = None
    if a.vocabulary_review:
        with open(a.vocabulary_review, encoding='utf-8-sig', newline='') as f:
            allowed = {r['token'] for r in csv.DictReader(f) if r['include'] == '1'}
    results = {cat: train_category(cat, rows, a, meta, allowed) for cat in a.categories}
    write_json(Path(a.out) / 'run_summary.json', results)

if __name__ == '__main__':
    main()
