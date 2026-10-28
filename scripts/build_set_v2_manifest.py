"""Build a non-destructive manifest revision with set-category support."""

from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from fashion_vn.text import LEXICON, category_hint, extract


ORIGINAL_CATEGORIES = {'dress', 'top', 'pants', 'skirt', 'jacket'}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('outputs/prepared/manifest.jsonl'))
    parser.add_argument('--out', type=Path, default=Path('outputs/prepared_set_v2'))
    parser.add_argument('--min-df', type=int, default=5)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    rows, changes = [], []
    with args.source.open(encoding='utf-8') as handle:
        for line in handle:
            row = json.loads(line)
            normalized, tokens, attributes, evidence, flags = extract(row['title_raw'])
            category = category_hint(normalized)
            if not normalized:
                flags.append('empty_title')
            if category not in ORIGINAL_CATEGORIES:
                flags.append('outside_original_five_categories')
            if category != row['category']:
                changes.append({
                    'product_id': row['product_id'],
                    'split': row['split'],
                    'old_category': row['category'],
                    'new_category': category,
                    'title_raw': row['title_raw'],
                })
            row.update(
                title_normalized=normalized,
                category=category,
                category_source='title_rule_set_v2',
                tokens=tokens,
                title_attributes=attributes,
                title_evidence=evidence,
                flags=flags,
            )
            rows.append(row)

    manifest = args.out / 'manifest.jsonl'
    with manifest.open('w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')

    with (args.out / 'category_changes.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['product_id', 'split', 'old_category', 'new_category', 'title_raw'])
        writer.writeheader()
        writer.writerows(changes)

    document_frequency = collections.Counter(
        token for row in rows if row['split'] == 'train' for token in set(row['tokens'])
    )
    with (args.out / 'vocabulary_review.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=['token', 'train_document_frequency', 'include', 'review_note'],
        )
        writer.writeheader()
        for token, count in document_frequency.most_common():
            writer.writerow({
                'token': token,
                'train_document_frequency': count,
                'include': int(count >= args.min_df),
                'review_note': '',
            })

    audit = {
        'source_manifest': str(args.source),
        'n_products': len(rows),
        'splits': dict(collections.Counter(row['split'] for row in rows)),
        'categories': dict(collections.Counter(row['category'] for row in rows)),
        'set_splits': dict(collections.Counter(row['split'] for row in rows if row['category'] == 'set')),
        'set_type_mentions': dict(collections.Counter(
            value
            for row in rows
            for value in row['title_attributes'].get('set_type', [])
        )),
        'category_changes': len(changes),
        'category_change_pairs': {
            f'{old} -> {new}': count
            for (old, new), count in sorted(collections.Counter(
                (change['old_category'], change['new_category']) for change in changes
            ).items())
        },
        'lexicon_groups': list(LEXICON),
        'note': 'Splits, duplicate groups, image hashes and image paths are preserved from the source manifest.',
    }
    write_json(args.out / 'audit.json', audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
