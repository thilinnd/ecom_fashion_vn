"""Extract reusable ImageNet feature maps. CNN is frozen in this local baseline."""
import argparse
import hashlib
import os
from pathlib import Path
import numpy as np
from PIL import Image
import torch
from torch.utils.data import Dataset, DataLoader
from .prepare import read_rows, write_json
from .model import Backbone, image_transform

class Images(Dataset):
    def __init__(self, rows, transform):
        self.rows, self.transform = rows, transform

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        with Image.open(self.rows[i]['image_path']) as im:
            return self.transform(im), i

def cache_key(row):
    return row['image_sha256']

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', default='outputs/prepared/manifest.jsonl')
    p.add_argument('--out', default='outputs/cache_resnet18')
    p.add_argument('--backbone', choices=['resnet18', 'inception_v3'], default='resnet18')
    p.add_argument('--batch-size', type=int, default=16)
    p.add_argument('--workers', type=int, default=0)
    p.add_argument('--threads', type=int, default=4)
    p.add_argument('--device', default='auto')
    p.add_argument('--backbone-checkpoint', help='Optional finetune/backbone.pt; cache is category-specific')
    a = p.parse_args()
    torch.set_num_threads(a.threads)
    os.environ.setdefault('TORCH_HOME', str(Path('.cache/torch').resolve()))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    meta_path = out / 'metadata.json'
    expected = {'backbone': a.backbone, 'pretraining': 'ImageNet1K', 'frozen': True,
                'transform': 'exif_rgb_letterbox_imagenet_norm_v1'}
    ck = None
    if a.backbone_checkpoint:
        ck = torch.load(a.backbone_checkpoint, map_location='cpu', weights_only=True)
        if ck['backbone'] != a.backbone:
            raise ValueError('Backbone name does not match checkpoint.')
        expected.update(frozen=False, category=ck['category'],
                        checkpoint_sha256=hashlib.sha256(Path(a.backbone_checkpoint).read_bytes()).hexdigest())
    if meta_path.exists():
        import json
        if json.loads(meta_path.read_text()) != expected:
            raise ValueError('Cache configuration differs; use another output directory.')
    write_json(meta_path, expected)
    rows = read_rows(a.manifest)
    if ck:
        rows = [r for r in rows if r['category'] == ck['category']]
    unique = {cache_key(r): r for r in rows if r['image_status'] == 'ok'}
    pending = [r for key, r in unique.items() if not (out / f'{key}.npy').exists()]
    if not pending:
        print('Cache complete; nothing to extract.')
        return
    device = ('cuda' if torch.cuda.is_available() else 'cpu') if a.device == 'auto' else a.device
    model = Backbone(a.backbone, pretrained=ck is None).to(device).eval()
    if ck:
        model.load_state_dict(ck['state_dict'])
    loader = DataLoader(Images(pending, image_transform(a.backbone)), batch_size=a.batch_size,
                        num_workers=a.workers)
    count = 0
    with torch.inference_mode():
        for images, indexes in loader:
            maps = model(images.to(device)).cpu().numpy().astype(np.float16)
            for feat, idx in zip(maps, indexes):
                r = pending[int(idx)]
                # Don't associate a changed image with an old hash.
                if hashlib.sha256(Path(r['image_path']).read_bytes()).hexdigest() != r['image_sha256']:
                    raise ValueError('Image changed since prepare; rerun prepare.')
                target = out / f'{cache_key(r)}.npy'
                temp = target.with_suffix('.tmp')
                with temp.open('wb') as f:
                    np.save(f, feat)
                temp.replace(target)
            count += len(indexes)
            if count % (a.batch_size * 10) == 0 or count == len(pending):
                print(f'{device}: cached {count}/{len(pending)} unique images', flush=True)

if __name__ == '__main__':
    main()
