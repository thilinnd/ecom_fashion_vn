"""Evaluate wide-form, image-only gold annotations against both prediction branches.

The input is the blind annotation sheet used by this project.  Only rows with a
non-empty annotator are treated as completed gold.  Unobservable or out-of-schema
groups are excluded instead of being converted to negative labels.
"""
import argparse
import collections
import csv
import json
import random
from pathlib import Path

from sklearn.metrics import average_precision_score

from .prepare import write_json
from .text import VISUAL_GROUPS


GROUPS = {
    "color": ("color_gold", [
        "đen", "trắng", "đỏ", "hồng", "xanh_dương", "xanh_lá", "xanh_navy",
        "vàng", "tím", "nâu", "xám", "be", "kem",
    ]),
    "sleeve": ("sleeve_gold", [
        "tay_dài", "tay_ngắn", "tay_lỡ", "không_tay", "tay_phồng", "tay_loe",
        "tay_raglan",
    ]),
    "neckline": ("neckline_gold", [
        "cổ_tròn", "cổ_v", "cổ_vuông", "cổ_lọ", "cổ_yếm", "cổ_đổ", "cổ_bẻ",
        "trễ_vai", "hai_dây", "một_vai",
    ]),
    "pattern": ("pattern_gold", [
        "trơn", "kẻ_sọc", "caro", "chấm_bi", "hoa", "in_hình", "loang", "da_báo",
    ]),
    "fit": ("fit_gold", ["rộng", "ôm", "suông"]),
    "length": ("length_gold", ["maxi", "midi", "mini", "croptop"]),
    "pant_cut": ("pant_cut_gold", [
        "ống_rộng", "ống_suông", "ống_loe", "ống_đứng", "ống_bó",
    ]),
    "waist": ("waist_gold", ["cạp_cao", "cạp_thấp"]),
    # Gold evaluation treats set_type as the parent binary label ``set``.
    # The four weak-label subtypes emitted by the trained head are collapsed
    # to this parent label in NORMALIZE below.
    "set_type": ("set_type_gold", ["set"]),
}
ATTRIBUTE_GROUP = {
    attribute: group for group, (_, attributes) in GROUPS.items() for attribute in attributes
}
EXCLUDED = {"", "unknown", "not_visible", "not_applicable", "other"}
NORMALIZE = {
    "un_known": "unknown",
    "gym_set": "set",
    "sports_set": "set",
    "ao_dai": "set",
    "casual_set": "set",
    "xán": "xám",
    "tay dài": "tay_dài",
    "cổ tròn": "cổ_tròn",
}


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize(value):
    value = value.strip().lower()
    return NORMALIZE.get(value, value)


def parse_gold(rows):
    completed = [row for row in rows if row.get("annotator", "").strip()]
    parsed = {}
    corrections = collections.Counter()
    excluded = collections.Counter()
    for row in completed:
        product_id = str(row["product_id"])
        groups = {}
        for group, (column, vocabulary) in GROUPS.items():
            # Backward compatibility: historical gold sheets predate set_type.
            if column not in row:
                continue
            raw_values = [part.strip().lower() for part in row[column].split(";")]
            values = []
            for raw in raw_values:
                value = normalize(raw)
                if value != raw:
                    corrections[f"{raw} -> {value}"] += 1
                values.append(value)
            if any(value in EXCLUDED for value in values):
                excluded[(group, next(value for value in values if value in EXCLUDED))] += 1
                continue
            invalid = sorted(set(values) - set(vocabulary))
            if invalid:
                raise ValueError(f"Unsupported gold value(s) for {product_id}/{group}: {invalid}")
            groups[group] = set(values)
        parsed[product_id] = {"row": row, "groups": groups}
    return parsed, corrections, excluded


def load_scores(path, product_ids):
    scores = collections.defaultdict(dict)
    selected = collections.defaultdict(set)
    for row in read_csv(path):
        product_id = str(row["product_id"])
        attribute = normalize(row["attribute"])
        if product_id not in product_ids or attribute not in ATTRIBUTE_GROUP:
            continue
        score = float(row["score"])
        scores[product_id][attribute] = max(score, scores[product_id].get(attribute, 0.0))
        if int(row["selected"]):
            selected[product_id].add(attribute)
    return scores, selected


def load_manifest(path, product_ids):
    categories = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            product_id = str(row["product_id"])
            if product_id in product_ids:
                categories[product_id] = row["category"]
    missing = product_ids - set(categories)
    if missing:
        raise ValueError(f"Gold products missing from manifest: {sorted(missing)[:5]}")
    return categories


def binary_metrics(items):
    tp = sum(y and p for y, p, _ in items)
    fp = sum(not y and p for y, p, _ in items)
    fn = sum(y and not p for y, p, _ in items)
    tn = sum(not y and not p for y, p, _ in items)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    return {
        "n": len(items), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
    }


def evaluate_subset(gold, scores, selected, product_ids):
    items = []
    per_attribute = collections.defaultdict(list)
    per_group = collections.defaultdict(list)
    group_rows = []
    product_items = collections.defaultdict(list)
    missing_scores = 0
    for product_id in product_ids:
        for group, gold_set in gold[product_id]["groups"].items():
            _, vocabulary = GROUPS[group]
            predicted_set = selected.get(product_id, set()) & set(vocabulary)
            group_pairs = []
            for attribute in vocabulary:
                y = attribute in gold_set
                pred = attribute in predicted_set
                score = scores.get(product_id, {}).get(attribute)
                if score is None:
                    score = 0.0
                    missing_scores += 1
                item = (y, pred, score)
                items.append(item)
                group_pairs.append(item)
                per_attribute[attribute].append(item)
                per_group[group].append(item)
                product_items[product_id].append(item)
            group_rows.append({
                "product_id": product_id,
                "group": group,
                "gold": ";".join(sorted(gold_set)),
                "predicted": ";".join(sorted(predicted_set)),
                "covered": bool(predicted_set),
                "exact_match": predicted_set == gold_set,
            })
    attribute_metrics = {}
    aps = []
    for attribute, attribute_items in sorted(per_attribute.items()):
        result = binary_metrics(attribute_items)
        y_true = [int(item[0]) for item in attribute_items]
        y_score = [item[2] for item in attribute_items]
        result["positive_support"] = sum(y_true)
        result["average_precision"] = (
            float(average_precision_score(y_true, y_score))
            if 0 < sum(y_true) < len(y_true) else None
        )
        if result["average_precision"] is not None:
            aps.append(result["average_precision"])
        attribute_metrics[attribute] = result
    group_metrics = {}
    for group, group_items in sorted(per_group.items()):
        matching = [row for row in group_rows if row["group"] == group]
        result = binary_metrics(group_items)
        result.update({
            "group_instances": len(matching),
            "coverage": sum(row["covered"] for row in matching) / len(matching),
            "exact_match_accuracy": sum(row["exact_match"] for row in matching) / len(matching),
            "selective_exact_match_accuracy": (
                sum(row["exact_match"] for row in matching if row["covered"])
                / sum(row["covered"] for row in matching)
                if any(row["covered"] for row in matching) else None
            ),
            "abstention_rate": 1 - sum(row["covered"] for row in matching) / len(matching),
        })
        group_metrics[group] = result
    covered_group_rows = [row for row in group_rows if row["covered"]]
    return {
        "micro": binary_metrics(items),
        "macro_f1": mean_or_none([
            value["f1"] for value in attribute_metrics.values()
            if value["f1"] is not None and value["positive_support"] > 0
        ]),
        "macro_map": mean_or_none(aps),
        "evaluated_products": len(product_ids),
        "evaluated_group_instances": len(group_rows),
        "group_coverage": sum(row["covered"] for row in group_rows) / len(group_rows),
        "group_exact_match_accuracy": sum(row["exact_match"] for row in group_rows) / len(group_rows),
        "selective_group_exact_match_accuracy": (
            sum(row["exact_match"] for row in covered_group_rows) / len(covered_group_rows)
            if covered_group_rows else None
        ),
        "group_abstention_rate": 1 - sum(row["covered"] for row in group_rows) / len(group_rows),
        "raw_score_pair_coverage": (len(items) - missing_scores) / len(items),
        "missing_score_pairs": missing_scores,
        "per_attribute": attribute_metrics,
        "per_group": group_metrics,
        "group_rows": group_rows,
        "product_items": product_items,
    }


def mean_or_none(values):
    return sum(values) / len(values) if values else None


def bootstrap_f1(product_items, seed=42, replicates=2000):
    product_ids = sorted(product_items)
    rng = random.Random(seed)
    estimates = []
    for _ in range(replicates):
        sampled = [rng.choice(product_ids) for _ in product_ids]
        items = [item for product_id in sampled for item in product_items[product_id]]
        value = binary_metrics(items)["f1"]
        if value is not None:
            estimates.append(value)
    estimates.sort()
    return {
        "method": "percentile bootstrap resampled by product",
        "seed": seed,
        "replicates": replicates,
        "lower_95": estimates[int(0.025 * len(estimates))],
        "upper_95": estimates[min(int(0.975 * len(estimates)), len(estimates) - 1)],
    }


def compact_result(result):
    return {
        "evaluated_products": result["evaluated_products"],
        "evaluated_group_instances": result["evaluated_group_instances"],
        "micro": result["micro"],
        "macro_f1": result["macro_f1"],
        "macro_map": result["macro_map"],
        "group_coverage": result["group_coverage"],
        "group_exact_match_accuracy": result["group_exact_match_accuracy"],
        "selective_group_exact_match_accuracy": result["selective_group_exact_match_accuracy"],
        "group_abstention_rate": result["group_abstention_rate"],
        "raw_score_pair_coverage": result["raw_score_pair_coverage"],
    }


def write_table(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_error_analysis(output_dir, prefix, result, group_rows):
    error_modes = collections.defaultdict(collections.Counter)
    attribute_confusions = collections.Counter()
    for row in group_rows:
        gold_set = {value for value in row["gold"].split(";") if value}
        predicted_set = {value for value in row["predicted"].split(";") if value}
        if predicted_set == gold_set:
            error_mode = "exact"
        elif not predicted_set:
            error_mode = "abstained"
        elif predicted_set & gold_set:
            error_mode = "partial_with_extra_or_missing"
        else:
            error_mode = "wrong_nonempty"
        error_modes[row["group"]][error_mode] += 1
        for gold_attribute in gold_set - predicted_set:
            for predicted_attribute in predicted_set - gold_set:
                attribute_confusions[(row["group"], gold_attribute, predicted_attribute)] += 1
    write_table(
        output_dir / f"{prefix}_group_error_modes.csv",
        [
            {
                "group": group,
                "group_instances": sum(counts.values()),
                "exact": counts["exact"],
                "abstained": counts["abstained"],
                "wrong_nonempty": counts["wrong_nonempty"],
                "partial_with_extra_or_missing": counts["partial_with_extra_or_missing"],
            }
            for group, counts in sorted(error_modes.items())
        ],
        ["group", "group_instances", "exact", "abstained", "wrong_nonempty",
         "partial_with_extra_or_missing"],
    )
    write_table(
        output_dir / f"{prefix}_attribute_confusions.csv",
        [
            {
                "group": group,
                "gold_attribute": gold_attribute,
                "predicted_attribute": predicted_attribute,
                "count": count,
                "gold_positive_support": result["per_attribute"][gold_attribute]["positive_support"],
                "count_over_gold_support": (
                    count / result["per_attribute"][gold_attribute]["positive_support"]
                ),
            }
            for (group, gold_attribute, predicted_attribute), count
            in sorted(attribute_confusions.items(), key=lambda item: (-item[1], item[0]))
        ],
        ["group", "gold_attribute", "predicted_attribute", "count",
         "gold_positive_support", "count_over_gold_support"],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", default="outputs/prepared/annotation_blind_100.csv")
    parser.add_argument("--out", default="outputs/evaluation_100")
    parser.add_argument("--manifest", default="outputs/prepared/manifest.jsonl")
    parser.add_argument("--schema-scores", default="outputs/predictions/image_scores.csv")
    parser.add_argument("--discovered-scores", default="outputs/predictions_discovered/image_scores.csv")
    parser.add_argument("--models", default="models/local_resnet18")
    parser.add_argument("--branches", nargs="+", choices=["schema", "discovered"], default=["schema", "discovered"])
    parser.add_argument("--bootstrap", type=int, default=2000)
    args = parser.parse_args()

    gold, corrections, excluded = parse_gold(read_csv(args.gold))
    if not gold:
        raise ValueError("No completed rows: annotator is empty for every row.")
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    branch_paths = {
        "schema": args.schema_scores,
        "discovered": args.discovered_scores,
    }
    branch_paths = {branch: branch_paths[branch] for branch in args.branches}
    categories = load_manifest(args.manifest, set(gold))
    visual_gold = {}
    visual_scope_excluded_groups = 0
    for product_id, item in gold.items():
        allowed_groups = VISUAL_GROUPS.get(categories[product_id], set())
        scoped_groups = {
            group: values for group, values in item["groups"].items()
            if group in allowed_groups
        }
        visual_scope_excluded_groups += len(item["groups"]) - len(scoped_groups)
        if scoped_groups:
            visual_gold[product_id] = {"row": item["row"], "groups": scoped_groups}
    schema_head_counts = json.load(open(Path(args.models) / "schema_summary.json", encoding="utf-8"))
    trained_categories = set(schema_head_counts)
    report = {
        "gold_file": str(args.gold),
        "completed_gold_rows": len(gold),
        "split_counts": dict(collections.Counter(item["row"]["split"] for item in gold.values())),
        "normalization_corrections": dict(corrections),
        "excluded_group_reasons": {
            f"{group}:{reason}": count for (group, reason), count in sorted(excluded.items())
        },
        "branches": {},
    }
    report["visual_scope"] = {
        "rules_source": "fashion_vn.text.VISUAL_GROUPS",
        "routing_basis": "title-derived category_hint from manifest",
        "eligible_products": len(visual_gold),
        "excluded_products_without_applicable_observable_groups": len(gold) - len(visual_gold),
        "excluded_group_instances": visual_scope_excluded_groups,
        "note": (
            "Conditional attribute evaluation only; category-routing accuracy is reported separately. "
            "An applicable group that has no trained head or fails the fixed threshold remains an error."
        ),
    }
    report["sample_profile"] = {
        "annotators": dict(collections.Counter(item["row"]["annotator"] for item in gold.values())),
        "category_gold": dict(collections.Counter(item["row"]["category_gold"] for item in gold.values())),
        "category_hint": dict(collections.Counter(categories[product_id] for product_id in gold)),
        "image_quality": dict(collections.Counter(item["row"]["image_quality"] for item in gold.values())),
        "multiple_products": dict(collections.Counter(item["row"]["multiple_products"] for item in gold.values())),
        "observable_group_instances": {
            group: sum(group in item["groups"] for item in gold.values()) for group in GROUPS
        },
    }
    for branch, score_path in branch_paths.items():
        scores, selected = load_scores(score_path, set(gold))
        all_result = evaluate_subset(gold, scores, selected, sorted(gold))
        visual_result = evaluate_subset(visual_gold, scores, selected, sorted(visual_gold))
        scored_ids = sorted(product_id for product_id in gold if scores.get(product_id))
        scored_result = evaluate_subset(gold, scores, selected, scored_ids) if scored_ids else None
        all_result["micro_f1_ci_95"] = bootstrap_f1(
            all_result.pop("product_items"), replicates=args.bootstrap
        )
        group_rows = all_result.pop("group_rows")
        visual_result["micro_f1_ci_95"] = bootstrap_f1(
            visual_result.pop("product_items"), replicates=args.bootstrap
        )
        visual_group_rows = visual_result.pop("group_rows")
        if scored_result:
            scored_result.pop("product_items")
            scored_result.pop("group_rows")
        statuses = {}
        for product_id in gold:
            category = categories[product_id]
            if category not in trained_categories:
                status = "no_category_model"
            elif branch == "schema" and schema_head_counts[category] == 0:
                status = "no_trained_attribute_heads"
            elif selected.get(product_id):
                status = "predicted_unvalidated"
            else:
                status = "abstained_no_standard_attribute"
            statuses[product_id] = status
        status_counts = collections.Counter(statuses.values())
        branch_report = {
            "fixed_export_threshold": 0.70,
            "fixed_runner_up_margin": 0.15,
            "prediction_status_counts": dict(status_counts),
            "products_with_any_exported_candidate": sum(
                bool(selected.get(product_id)) for product_id in gold
            ),
            "product_candidate_coverage": sum(
                bool(selected.get(product_id)) for product_id in gold
            ) / len(gold),
            "end_to_end": all_result,
            "visual_scope_conditional": visual_result,
            "scored_subset_diagnostic": scored_result,
            "subgroup_diagnostics": {},
            "visual_scope_subgroup_diagnostics": {},
        }
        subgroup_ids = {
            "quality_good": [p for p, item in gold.items() if item["row"]["image_quality"] == "good"],
            "quality_usable": [p for p, item in gold.items() if item["row"]["image_quality"] == "usable"],
            "single_product": [p for p, item in gold.items() if item["row"]["multiple_products"] == "no"],
            "multiple_products": [p for p, item in gold.items() if item["row"]["multiple_products"] == "yes"],
            "category_route_match": [
                p for p, item in gold.items() if item["row"]["category_gold"] == categories[p]
            ],
            "category_route_mismatch": [
                p for p, item in gold.items() if item["row"]["category_gold"] != categories[p]
            ],
        }
        for split in sorted({item["row"]["split"] for item in gold.values()}):
            subgroup_ids[f"split_{split}"] = [
                product_id
                for product_id, item in gold.items()
                if item["row"]["split"] == split
            ]
        for category_gold in sorted(
            {item["row"]["category_gold"] for item in gold.values()}
        ):
            subgroup_ids[f"gold_category_{category_gold}"] = [
                product_id
                for product_id, item in gold.items()
                if item["row"]["category_gold"] == category_gold
            ]
        for subgroup, subgroup_product_ids in subgroup_ids.items():
            branch_report["subgroup_diagnostics"][subgroup] = compact_result(
                evaluate_subset(gold, scores, selected, subgroup_product_ids)
            )
            visual_subgroup_ids = [
                product_id for product_id in subgroup_product_ids if product_id in visual_gold
            ]
            if visual_subgroup_ids:
                branch_report["visual_scope_subgroup_diagnostics"][subgroup] = compact_result(
                    evaluate_subset(visual_gold, scores, selected, visual_subgroup_ids)
                )
        report["branches"][branch] = branch_report
        attribute_rows = []
        for attribute, values in all_result["per_attribute"].items():
            attribute_rows.append({"attribute": attribute, "group": ATTRIBUTE_GROUP[attribute], **values})
        write_table(
            output_dir / f"{branch}_per_attribute.csv", attribute_rows,
            ["attribute", "group", "n", "positive_support", "tp", "fp", "fn", "tn",
             "precision", "recall", "f1", "average_precision"],
        )
        group_metric_rows = [{"group": group, **values} for group, values in all_result["per_group"].items()]
        write_table(
            output_dir / f"{branch}_per_group.csv", group_metric_rows,
            ["group", "group_instances", "n", "tp", "fp", "fn", "tn", "precision",
             "recall", "f1", "coverage", "exact_match_accuracy",
             "selective_exact_match_accuracy", "abstention_rate"],
        )
        write_error_analysis(output_dir, branch, all_result, group_rows)
        write_table(
            output_dir / f"{branch}_group_predictions.csv", group_rows,
            ["product_id", "group", "gold", "predicted", "covered", "exact_match"],
        )
        visual_attribute_rows = [
            {"attribute": attribute, "group": ATTRIBUTE_GROUP[attribute], **values}
            for attribute, values in visual_result["per_attribute"].items()
        ]
        write_table(
            output_dir / f"{branch}_visual_scope_per_attribute.csv", visual_attribute_rows,
            ["attribute", "group", "n", "positive_support", "tp", "fp", "fn", "tn",
             "precision", "recall", "f1", "average_precision"],
        )
        visual_group_metric_rows = [
            {"group": group, **values} for group, values in visual_result["per_group"].items()
        ]
        write_table(
            output_dir / f"{branch}_visual_scope_per_group.csv", visual_group_metric_rows,
            ["group", "group_instances", "n", "tp", "fp", "fn", "tn", "precision",
             "recall", "f1", "coverage", "exact_match_accuracy",
             "selective_exact_match_accuracy", "abstention_rate"],
        )
        write_error_analysis(
            output_dir, f"{branch}_visual_scope", visual_result, visual_group_rows
        )
        write_table(
            output_dir / f"{branch}_visual_scope_group_predictions.csv", visual_group_rows,
            ["product_id", "group", "gold", "predicted", "covered", "exact_match"],
        )

    category_confusion = collections.Counter()
    category_correct = 0
    for product_id, item in gold.items():
        predicted = categories[product_id]
        actual = item["row"]["category_gold"]
        category_confusion[(actual, predicted)] += 1
        category_correct += actual == predicted
    report["category_routing"] = {
        "accuracy": category_correct / len(gold),
        "correct": category_correct,
        "n": len(gold),
        "note": "category_hint is title-derived routing, not an image category classifier",
    }
    write_table(
        output_dir / "category_confusion.csv",
        [
            {"category_gold": actual, "category_hint": predicted, "count": count}
            for (actual, predicted), count in sorted(category_confusion.items())
        ],
        ["category_gold", "category_hint", "count"],
    )
    write_json(output_dir / "evaluation_summary.json", report)
    concise = {
        "completed_gold_rows": report["completed_gold_rows"],
        "split_counts": report["split_counts"],
        "category_routing": report["category_routing"],
        "branches": {
            branch: {
                "product_candidate_coverage": values["product_candidate_coverage"],
                "prediction_status_counts": values["prediction_status_counts"],
                "end_to_end": compact_result(values["end_to_end"]),
                "micro_f1_ci_95": values["end_to_end"]["micro_f1_ci_95"],
                "visual_scope_conditional": compact_result(values["visual_scope_conditional"]),
                "visual_scope_micro_f1_ci_95": values["visual_scope_conditional"]["micro_f1_ci_95"],
            }
            for branch, values in report["branches"].items()
        },
    }
    print(json.dumps(concise, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
