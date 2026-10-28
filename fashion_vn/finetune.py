"""Optional end-to-end CNN fine-tuning after a frozen-backbone warm start."""
import argparse
import os
from pathlib import Path
import torch
from torch.utils.data import DataLoader
from .cache import Images
from .model import Backbone, JointEmbedding, image_transform, ranking_loss
from .prepare import read_rows, write_json
from .train import bow_tensor

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', default='outputs/prepared/manifest.jsonl')
    p.add_argument('--vse', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--epochs', type=int, default=10)
    p.add_argument('--batch-size', type=int, default=16)
    p.add_argument('--lr', type=float, default=1e-5)
    p.add_argument('--device', default='auto')
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--threads', type=int, default=4)
    a = p.parse_args()
    if a.batch_size < 2:
        p.error('Contrastive training requires batch-size >= 2')
    torch.manual_seed(a.seed)
    torch.set_num_threads(a.threads)
    os.environ.setdefault('TORCH_HOME', str(Path('.cache/torch').resolve()))
    device = ('cuda' if torch.cuda.is_available() else 'cpu') if a.device == 'auto' else a.device
    ck = torch.load(a.vse, map_location='cpu', weights_only=True)
    if not ck['cache_metadata']['frozen']:
        raise ValueError('This command expects an ImageNet frozen-backbone warm start.')
    name = ck['cache_metadata']['backbone']
    backbone = Backbone(name).to(device)
    model = JointEmbedding(ck['channels'], len(ck['vocab']), ck['dim']).to(device)
    model.load_state_dict(ck['state_dict'])
    rows = [r for r in read_rows(a.manifest) if r['category'] == ck['category'] and r['image_status'] == 'ok'
            and set(r['tokens']).intersection(ck['vocab'])
            and not any(f in r['flags'] for f in ('listing_multiple_variants', 'possible_negation_review'))]
    groups = {g: i for i, g in enumerate(sorted({r['group_id'] for r in rows}))}
    datasets = {}
    for split in ('train', 'val'):
        rs = [r for r in rows if r['split'] == split]
        if len(rs) < 2:
            raise ValueError(f'Insufficient {split} data')
        datasets[split] = (DataLoader(Images(rs, image_transform(name)), batch_size=a.batch_size,
                                     shuffle=split == 'train', num_workers=0),
                           bow_tensor(rs, ck['vocab']), torch.tensor([groups[r['group_id']] for r in rs]))
    optimizer = torch.optim.AdamW([
        {'params': backbone.parameters(), 'lr': a.lr},
        {'params': model.parameters(), 'lr': a.lr*10}], weight_decay=1e-4)
    best, history = float('inf'), []
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for epoch in range(a.epochs):
        losses = {}
        for split in ('train', 'val'):
            training = split == 'train'
            model.train(training)
            backbone.train(training)
            # Keep pretrained running BN stats stable for small local batches.
            for layer in backbone.modules():
                if isinstance(layer, torch.nn.modules.batchnorm._BatchNorm):
                    layer.eval()
            loader, B, G = datasets[split]
            total, count = 0., 0
            with torch.set_grad_enabled(training):
                for images, ix in loader:
                    if len(ix) < 2:
                        continue
                    b, g = B[ix].to(device), G[ix].to(device)
                    features = backbone(images.to(device)).mean((2, 3))
                    loss = ranking_loss(model.image(features), model.text(b), g, b)
                    if training:
                        optimizer.zero_grad()
                        loss.backward()
                        torch.nn.utils.clip_grad_norm_(list(backbone.parameters()) + list(model.parameters()), 5)
                        optimizer.step()
                    total += loss.item() * len(ix)
                    count += len(ix)
            losses[split] = total / max(count, 1)
        history.append(dict(epoch=epoch+1, **losses))
        print(history[-1], flush=True)
        if losses['val'] < best:
            best = losses['val']
            torch.save({'state_dict': {k: v.cpu() for k, v in backbone.state_dict().items()},
                        'backbone': name, 'category': ck['category'], 'method': 'vse_end_to_end'}, out/'backbone.pt')
            saved = dict(ck)
            saved['state_dict'] = {k: v.cpu() for k, v in model.state_dict().items()}
            saved['method'] = 'end_to_end_spatial_vse_v1'
            torch.save(saved, out/'vse.pt')
    write_json(out/'finetune_history.json', history)

if __name__ == '__main__':
    main()
