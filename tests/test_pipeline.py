import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from fashion_vn.text import extract, category_hint

class TextTests(unittest.TestCase):
    def test_vietnamese_compounds_and_seller_claims(self):
        _, tokens, attrs, evidence, flags = extract('ÁO thun tay lỡ form rộng 8 màu 100% Cotton')
        self.assertIn('tay_lỡ', tokens)
        self.assertEqual(attrs['fit'], ['rộng'])
        self.assertEqual(attrs['material_claim'], ['cotton'])
        self.assertIn('listing_multiple_variants', flags)
        self.assertTrue(all(e['source'] == 'title_rule' for e in evidence))

    def test_ambiguous_color_not_invented(self):
        _, _, attrs, _, flags = extract('Áo xanh')
        self.assertNotIn('color', attrs)
        self.assertIn('ambiguous_xanh', flags)

    def test_category_hood_not_hat(self):
        self.assertEqual(category_hint('Áo khoác gió có mũ rộng'), 'jacket')
        self.assertEqual(category_hint('Mũ lưỡi trai cotton'), 'hat')
        self.assertEqual(category_hint('Chân váy nữ'), 'skirt')

    def test_set_category_and_ao_dai_disambiguation(self):
        self.assertEqual(category_hint('Bộ tập gym nữ áo croptop quần dài'), 'set')
        self.assertEqual(category_hint('Quần áo bóng đá trẻ em'), 'set')
        self.assertEqual(category_hint('Áo dài truyền thống nữ kèm quần'), 'set')
        self.assertEqual(category_hint('Áo dài tay giữ nhiệt nam'), 'top')
        self.assertEqual(category_hint('Quần lụa mặc bên trong áo dài Tết'), 'pants')
        self.assertEqual(category_hint('Áo dài nam cách tân không kèm quần'), 'top')

    def test_set_type_weak_labels(self):
        self.assertEqual(extract('Bộ tập gym nữ áo croptop quần dài')[2]['set_type'], ['gym_set'])
        self.assertEqual(extract('Áo dài truyền thống nữ kèm quần')[2]['set_type'], ['ao_dai'])

    def test_negation_flagged(self):
        self.assertIn('possible_negation_review', extract('Áo không phải cotton')[4])

class IntegrityTests(unittest.TestCase):
    def test_group_split_and_missing_image(self):
        import openpyxl
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            Image.new('RGB', (32, 32), 'red').save(root / 'a.png')
            (root / 'b.png').write_bytes((root / 'a.png').read_bytes())
            w = openpyxl.Workbook()
            s = w.active
            s.append(['product_id', 'product', 'img_local_path'])
            s.append([1, 'Áo đỏ tay dài', 'a.png'])
            s.append([2, 'Áo đỏ tay ngắn', 'b.png'])
            s.append([3, 'Áo đỏ tay ngắn', 'missing.png'])
            w.save(root / 'data.xlsx')
            subprocess.run([sys.executable, '-m', 'fashion_vn.prepare', '--xlsx', str(root/'data.xlsx'),
                            '--image-root', str(root), '--out', str(root/'out')],
                           check=True, capture_output=True)
            records = [json.loads(x) for x in (root/'out/manifest.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len({r['group_id'] for r in records}), 1)
            self.assertEqual(len({r['split'] for r in records}), 1)
            self.assertEqual(records[2]['image_status'], 'missing')

    def test_evaluation_unknown_and_missing_predictions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/'gold.csv').write_text('product_id,split,concept,attribute,label,annotator\n'
                                        '1,test,color,red,present,A\n2,test,color,red,unknown,A\n'
                                        '3,test,color,red,absent,A\n', encoding='utf-8')
            (root/'scores.csv').write_text('product_id,split,attribute,score,selected\n'
                                          '3,test,red,0.9,1\n', encoding='utf-8')
            subprocess.run([sys.executable, '-m', 'fashion_vn.evaluate', '--gold', str(root/'gold.csv'),
                            '--scores', str(root/'scores.csv'), '--out', str(root/'eval.json')],
                           check=True, capture_output=True)
            result = json.loads((root/'eval.json').read_text())
            self.assertEqual(result['micro']['fn'], 1)
            self.assertEqual(result['micro']['fp'], 1)
            self.assertEqual(result['excluded_unknown'], 1)

class ModelTests(unittest.TestCase):
    def test_train_predict_roundtrip_synthetic(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cache = root/'cache'
            cache.mkdir()
            (cache/'metadata.json').write_text(json.dumps({'backbone':'resnet18', 'frozen':True}))
            vocab = ['đen', 'trắng', 'tay_dài', 'tay_ngắn', 'cổ_tròn', 'cổ_v', 'maxi', 'mini']
            rows = []
            rng = np.random.default_rng(42)
            for i in range(240):
                np.save(cache/f'{i}.npy', rng.normal(size=(8,7,7)).astype(np.float16))
                rows.append(dict(product_id=str(i), title_raw='SYNTHETIC TEST ONLY', category='top',
                                 image_status='ok', image_sha256=str(i), image_path='synthetic',
                                 split='train' if i<160 else 'val' if i<200 else 'test',
                                 group_id=str(i), tokens=[vocab[i%8]], flags=[],
                                 title_attributes={['color','sleeve','neckline','length'][(i%8)//2]:[vocab[i%8]]},
                                 title_evidence=[]))
            manifest = root/'manifest.jsonl'
            manifest.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
            command = [sys.executable, '-m', 'fashion_vn.train', '--manifest', str(manifest),
                       '--cache', str(cache), '--out', str(root/'models'), '--categories', 'top',
                       '--epochs', '2', '--head-epochs', '2', '--dim', '16', '--min-products', '10',
                       '--min-head-examples', '3', '--min-df', '2', '--threads', '1']
            completed = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            pred = subprocess.run([sys.executable, '-m', 'fashion_vn.predict', '--manifest', str(manifest),
                                   '--cache', str(cache), '--models', str(root/'models'),
                                   '--out', str(root/'pred')], capture_output=True, text=True)
            self.assertEqual(pred.returncode, 0, pred.stderr)
            summary = json.loads((root/'pred/summary.json').read_text())
            self.assertEqual(summary['n_products'], 240)
            self.assertFalse(summary['gold_evaluation_performed'])
            self.assertTrue((root/'pred/fashion_vn_attributes.xlsx').exists())
            fitted = subprocess.run([sys.executable, '-m', 'fashion_vn.schema_heads',
                                     '--manifest', str(manifest), '--cache', str(cache),
                                     '--models', str(root/'models'), '--epochs', '2'],
                                    capture_output=True, text=True)
            self.assertEqual(fitted.returncode, 0, fitted.stderr)
            count = json.loads((root/'models/schema_summary.json').read_text())['top']
            self.assertGreater(count, 0)
            fitted_pred = subprocess.run([sys.executable, '-m', 'fashion_vn.predict', '--head-type', 'schema',
                                          '--manifest', str(manifest), '--cache', str(cache),
                                          '--models', str(root/'models'), '--out', str(root/'schema_pred')],
                                         capture_output=True, text=True)
            self.assertEqual(fitted_pred.returncode, 0, fitted_pred.stderr)
            self.assertEqual(json.loads((root/'schema_pred/summary.json').read_text())['head_type'], 'schema')

    def test_eaam_conservation(self):
        import torch
        from fashion_vn.model import JointEmbedding
        torch.manual_seed(42)
        model = JointEmbedding(4, 3, 5)
        maps = torch.randn(4, 8, 8)
        weights = model.word_embedding.weight @ model.image_projection.weight
        activation = torch.einsum('ac,cij->aij', weights, maps)
        dot = model.word_embedding.weight @ model.image_projection(maps.mean((1,2)))
        torch.testing.assert_close(activation.mean((1,2)), dot)

    def test_duplicate_descriptions_not_false_negatives(self):
        import torch
        from fashion_vn.model import ranking_loss
        x = torch.eye(2)
        bow = torch.ones(2, 3)
        loss = ranking_loss(x, x, torch.tensor([0, 1]), bow)
        self.assertEqual(float(loss), 0.0)

if __name__ == '__main__':
    unittest.main()
