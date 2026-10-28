"""Export representative product images for selected discovered clusters.

The export is intended for human review.  It mirrors the VSE training filters,
then creates deterministic, term-balanced samples with either one cluster term
or multiple co-occurring cluster terms in the product title.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path


DEFAULT_LABELS = {
    7: "tshirt_loose_fit",
    22: "shirt_linen_dui",
    11: "activewear_gym",
    18: "feminine_decoration",
    19: "body_fit_silhouette",
    27: "hoodie_zip",
    29: "generic_color_mixed",
}
FORBIDDEN_FLAGS = {"listing_multiple_variants", "possible_negation_review"}


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def read_composition(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {int(row["concept_id"]): row for row in rows}


def balanced_sample(rows, representative_terms, limit, seed):
    """Round-robin over representative terms, then fill deterministically."""
    if limit == 0 or len(rows) <= limit:
        return sorted(rows, key=lambda item: int(item["row"]["product_id"]))

    rng = random.Random(seed)
    shuffled = list(rows)
    rng.shuffle(shuffled)
    queues = {
        term: [item for item in shuffled if term in item["hits"]]
        for term in representative_terms
    }
    selected = []
    selected_ids = set()
    while len(selected) < limit:
        added = False
        for term in representative_terms:
            queue = queues[term]
            while queue and queue[0]["row"]["product_id"] in selected_ids:
                queue.pop(0)
            if queue and len(selected) < limit:
                item = queue.pop(0)
                selected.append(item)
                selected_ids.add(item["row"]["product_id"])
                added = True
        if not added:
            break

    remaining = [
        item for item in shuffled if item["row"]["product_id"] not in selected_ids
    ]
    remaining.sort(
        key=lambda item: (
            -len(item["representative_hits"]),
            -len(item["hits"]),
            int(item["row"]["product_id"]),
        )
    )
    selected.extend(remaining[: max(0, limit - len(selected))])
    return selected


def safe_copy(source: Path, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def write_csv(path: Path, rows, fieldnames):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", default="outputs/prepared_set_v2/manifest.jsonl"
    )
    parser.add_argument(
        "--concepts", default="models/local_resnet18_set_v2/top/concepts.json"
    )
    parser.add_argument(
        "--composition",
        default="outputs/figures/spatial_concepts/3_7_4_top_concept_composition.csv",
    )
    parser.add_argument(
        "--out", default="outputs/cluster_product_images/top_selected_clusters"
    )
    parser.add_argument(
        "--cluster-ids", nargs="+", type=int, default=sorted(DEFAULT_LABELS)
    )
    parser.add_argument("--single-limit", type=int, default=20)
    parser.add_argument("--multi-limit", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.single_limit < 0 or args.multi_limit < 0:
        parser.error("sample limits must be non-negative; use 0 to export all")

    concepts = {
        int(item["concept_id"]): set(item["attributes"])
        for item in json.loads(Path(args.concepts).read_text(encoding="utf-8"))
    }
    unknown = sorted(set(args.cluster_ids) - set(concepts))
    if unknown:
        parser.error(f"unknown cluster ids: {unknown}")

    composition = read_composition(Path(args.composition))
    rows = [
        row
        for row in read_jsonl(Path(args.manifest))
        if row["category"] == "top"
        and row["split"] == "train"
        and row["image_status"] == "ok"
        and not (set(row["flags"]) & FORBIDDEN_FLAGS)
    ]
    output_root = Path(args.out)
    output_root.mkdir(parents=True, exist_ok=True)
    summary_rows = []

    for cluster_id in args.cluster_ids:
        attributes = concepts[cluster_id]
        composition_row = composition.get(cluster_id, {})
        representative_terms = [
            value.strip()
            for value in composition_row.get("representative_terms", "").split(",")
            if value.strip()
        ]
        label = DEFAULT_LABELS.get(cluster_id, f"cluster_{cluster_id:02d}")
        cluster_dir = output_root / f"cluster_{cluster_id:02d}_{label}"
        single_dir = cluster_dir / "single_term_evidence"
        multi_dir = cluster_dir / "multi_term_evidence"
        single_dir.mkdir(parents=True, exist_ok=True)
        multi_dir.mkdir(parents=True, exist_ok=True)

        matches = []
        term_counts = Counter()
        for row in rows:
            hits = attributes.intersection(row["tokens"])
            if not hits:
                continue
            representative_hits = set(representative_terms).intersection(hits)
            matches.append(
                {
                    "row": row,
                    "hits": hits,
                    "representative_hits": representative_hits,
                }
            )
            term_counts.update(hits)

        single = [item for item in matches if len(item["hits"]) == 1]
        multi = [item for item in matches if len(item["hits"]) >= 2]
        selected_single = balanced_sample(
            single, representative_terms, args.single_limit, args.seed + cluster_id
        )
        selected_multi = balanced_sample(
            multi, representative_terms, args.multi_limit, args.seed + 1000 + cluster_id
        )

        index_rows = []
        for sample_type, selected, destination_dir in (
            ("single_term", selected_single, single_dir),
            ("multi_term", selected_multi, multi_dir),
        ):
            for rank, item in enumerate(selected, start=1):
                row = item["row"]
                source = Path(row["image_path"])
                if not source.exists():
                    raise FileNotFoundError(source)
                suffix = source.suffix.lower() or ".jpg"
                destination = destination_dir / (
                    f"{rank:03d}_product_{row['product_id']}{suffix}"
                )
                safe_copy(source, destination)
                index_rows.append(
                    {
                        "sample_type": sample_type,
                        "rank": rank,
                        "product_id": row["product_id"],
                        "matched_terms": ";".join(sorted(item["hits"])),
                        "representative_hits": ";".join(
                            sorted(item["representative_hits"])
                        ),
                        "title_raw": row["title_raw"],
                        "source_image": str(source),
                        "exported_image": str(destination),
                        "image_sha256": row["image_sha256"],
                    }
                )

        write_csv(
            cluster_dir / "index.csv",
            index_rows,
            [
                "sample_type",
                "rank",
                "product_id",
                "matched_terms",
                "representative_hits",
                "title_raw",
                "source_image",
                "exported_image",
                "image_sha256",
            ],
        )
        write_csv(
            cluster_dir / "all_matching_products.csv",
            [
                {
                    "product_id": item["row"]["product_id"],
                    "matched_terms": ";".join(sorted(item["hits"])),
                    "match_count": len(item["hits"]),
                    "title_raw": item["row"]["title_raw"],
                    "image_path": item["row"]["image_path"],
                    "image_sha256": item["row"]["image_sha256"],
                }
                for item in sorted(
                    matches, key=lambda value: int(value["row"]["product_id"])
                )
            ],
            [
                "product_id",
                "matched_terms",
                "match_count",
                "title_raw",
                "image_path",
                "image_sha256",
            ],
        )
        readme = (
            f"# Top cluster {cluster_id}: {label}\n\n"
            f"- Vocabulary size: {composition_row.get('size', len(attributes))}\n"
            f"- Training mentions: {composition_row.get('training_mentions', '')}\n"
            f"- Representative terms: {', '.join(representative_terms)}\n"
            f"- Matching safe train products: {len(matches)}\n"
            f"- Single-term products: {len(single)}; exported: {len(selected_single)}\n"
            f"- Multi-term products: {len(multi)}; exported: {len(selected_multi)}\n"
            f"- Most frequent matched terms: "
            + ", ".join(f"{term} ({count})" for term, count in term_counts.most_common(10))
            + "\n\n"
            "`single_term_evidence` contains products with exactly one cluster term in "
            "the normalized title. `multi_term_evidence` contains products with two or "
            "more co-occurring cluster terms. These are weak-title evidence samples, not "
            "human-confirmed cluster membership. See `index.csv` for traceability and "
            "`all_matching_products.csv` for the complete matching set.\n"
        )
        (cluster_dir / "README.md").write_text(readme, encoding="utf-8")
        summary_rows.append(
            {
                "cluster_id": cluster_id,
                "label": label,
                "vocabulary_size": composition_row.get("size", len(attributes)),
                "training_mentions": composition_row.get("training_mentions", ""),
                "representative_terms": ";".join(representative_terms),
                "matching_products": len(matches),
                "single_term_products": len(single),
                "multi_term_products": len(multi),
                "exported_single": len(selected_single),
                "exported_multi": len(selected_multi),
                "folder": str(cluster_dir),
            }
        )

    write_csv(
        output_root / "cluster_export_summary.csv",
        summary_rows,
        [
            "cluster_id",
            "label",
            "vocabulary_size",
            "training_mentions",
            "representative_terms",
            "matching_products",
            "single_term_products",
            "multi_term_products",
            "exported_single",
            "exported_multi",
            "folder",
        ],
    )
    root_readme = (
        "# Representative product images for selected top clusters\n\n"
        "Each cluster folder contains deterministic, term-balanced samples for human "
        "review. The export mirrors the VSE train eligibility filters and excludes "
        "multiple-variant or possible-negation rows. Cluster membership is inferred "
        "from weak title tokens and must not be treated as human gold.\n\n"
        "Run again with `--single-limit 0 --multi-limit 0` to copy every matching "
        "training product.\n"
    )
    (output_root / "README.md").write_text(root_readme, encoding="utf-8")
    print(
        f"Exported {sum(row['exported_single'] + row['exported_multi'] for row in summary_rows)} "
        f"images across {len(summary_rows)} cluster folders to {output_root.resolve()}"
    )


if __name__ == "__main__":
    main()
