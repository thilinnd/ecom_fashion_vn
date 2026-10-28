"""Create English-language figures for discovered-knowledge results."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import davies_bouldin_score, silhouette_score
from sklearn.preprocessing import normalize as l2_normalize


CATEGORY_ORDER = ["top", "dress", "pants", "skirt", "jacket", "bag", "hat", "set"]
CATEGORY_LABELS = {
    "top": "Top",
    "dress": "Dress",
    "pants": "Pants",
    "skirt": "Skirt",
    "jacket": "Jacket",
    "bag": "Bag",
    "hat": "Hat",
    "set": "Set",
}

# Attribute labels follow the Vietnamese terminology used in the report.
CANDIDATES = [
    ("Dáng xòe", "Silhouette", [r"\bxòe\b", r"\bxoè\b"]),
    ("Cúc, nút hoặc khuy", "Construction", [r"\bcúc\b", r"\bnút\b", r"\bkhuy\b"]),
    ("Bèo hoặc nhún", "Decoration", [r"\bbèo\b", r"\bnhún\b"]),
    ("Xếp ly", "Construction", [r"\bxếp ly\b", r"\bxếp li\b"]),
    ("Thêu", "Decoration", [r"\bthêu\b"]),
    ("Nơ", "Decoration", [r"\bnơ\b"]),
    ("Đính kết", "Decoration", [r"\bđính\b"]),
    ("Khóa kéo hoặc zip", "Construction", [r"\bkhóa kéo\b", r"\bkhoá kéo\b", r"\bzip\b"]),
    ("Xẻ tà", "Construction", [r"\bxẻ tà\b"]),
    ("Lưới", "Surface / texture", [r"\blưới\b"]),
    ("Đuôi cá", "Silhouette", [r"\bđuôi cá\b"]),
    ("Boxy", "Silhouette", [r"\bboxy\b"]),
    ("Babydoll", "Silhouette", [r"\bbabydoll\b"]),
    ("Dây rút", "Construction", [r"\bdây rút\b"]),
    ("Bút chì", "Silhouette", [r"\bbút chì\b"]),
    ("Túi hộp", "Construction", [r"\btúi hộp\b"]),
    ("Xuyên thấu", "Surface / texture", [r"\bxuyên thấu\b"]),
    ("Peplum", "Silhouette", [r"\bpeplum\b"]),
]

CANDIDATE_COLORS = {
    "Silhouette": "#5b8db8",
    "Construction": "#d97757",
    "Decoration": "#8b6bb1",
    "Surface / texture": "#55a487",
}

COHERENCE_PAIRS = [
    ("dress", "xếp", "ly", "Xếp–ly — dress"),
    ("skirt", "xếp", "ly", "Xếp–ly — skirt"),
    ("dress", "xẻ", "tà", "Xẻ–tà — dress"),
    ("skirt", "xẻ", "tà", "Xẻ–tà — skirt"),
    ("skirt", "xòe", "tầng", "Xòe–tầng — skirt"),
    ("top", "bèo", "nhún", "Bèo–nhún — top"),
    ("top", "thêu", "nơ", "Thêu–nơ — top"),
    ("jacket", "boxy", "lửng", "Boxy–lửng — jacket"),
    ("pants", "dây", "rút", "Dây–rút — pants"),
    ("bag", "chống", "nước", "Chống–nước — bag"),
    ("hat", "chống", "nắng", "Chống–nắng — hat"),
    ("pants", "tập", "gym", "Tập–gym — pants"),
    ("hat", "dệt", "kim", "Dệt–kim — hat"),
]


def save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_dir / f"{stem}.png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(output_dir / f"{stem}.svg", bbox_inches="tight", facecolor="white")


def load_discovery_summary(summary_csv: Path, model_root: Path) -> pd.DataFrame:
    summary = pd.read_csv(summary_csv, encoding="utf-8-sig").set_index("category")
    records = []
    for category in CATEGORY_ORDER:
        archive = np.load(model_root / category / "attribute_representations.npz")
        joint = np.concatenate(
            [l2_normalize(archive["spatial"]), l2_normalize(archive["semantic"])],
            axis=1,
        )
        clusters = archive["clusters"]
        row = summary.loc[category]
        records.append(
            {
                "category": category,
                "train_products": int(row["train_products"]),
                "vocabulary": int(row["vocabulary"]),
                "concepts": int(row["discovered_concepts"]),
                "heads": int(row["trained_heads"]),
                "silhouette": float(silhouette_score(joint, clusters)),
                "davies_bouldin": float(davies_bouldin_score(joint, clusters)),
            }
        )
    return pd.DataFrame(records)


def plot_discovery_overview(summary: pd.DataFrame, output_dir: Path) -> None:
    labels = [CATEGORY_LABELS[item] for item in summary["category"]]
    positions = np.arange(len(summary))
    fig, axes = plt.subplots(1, 3, figsize=(17, 6.5))

    bars = axes[0].bar(positions, summary["vocabulary"], color="#5b8db8")
    axes[0].set_xticks(positions, labels, rotation=35, ha="right")
    axes[0].set_ylabel("Vocabulary items")
    axes[0].set_title("(a) Discovery vocabulary", fontweight="bold")
    for bar, value in zip(bars, summary["vocabulary"]):
        axes[0].text(bar.get_x() + bar.get_width() / 2, value + 9, str(value), ha="center", fontsize=9)

    width = 0.38
    axes[1].bar(positions - width / 2, summary["concepts"], width, label="Discovered concepts", color="#9fb9cf")
    axes[1].bar(positions + width / 2, summary["heads"], width, label="Trainable heads", color="#d97757")
    axes[1].set_xticks(positions, labels, rotation=35, ha="right")
    axes[1].set_ylabel("Count")
    axes[1].set_ylim(0, 34)
    axes[1].set_title("(b) Concept capacity", fontweight="bold")
    axes[1].legend(frameon=False, loc="lower left")
    for x, concept, head in zip(positions, summary["concepts"], summary["heads"]):
        axes[1].text(x - width / 2, concept + 0.6, str(concept), ha="center", fontsize=8)
        axes[1].text(x + width / 2, head + 0.6, str(head), ha="center", fontsize=8)

    quality = axes[2].bar(positions, summary["silhouette"], color="#55a487")
    axes[2].set_xticks(positions, labels, rotation=35, ha="right")
    axes[2].set_ylabel("Silhouette coefficient")
    axes[2].set_ylim(0, 0.21)
    axes[2].set_title("(c) Cluster separation", fontweight="bold")
    for bar, silhouette, db in zip(quality, summary["silhouette"], summary["davies_bouldin"]):
        axes[2].text(
            bar.get_x() + bar.get_width() / 2,
            silhouette + 0.005,
            f"{silhouette:.3f}\nDB={db:.2f}",
            ha="center",
            fontsize=8,
        )

    for ax in axes:
        ax.grid(axis="y", alpha=0.22)
        ax.set_axisbelow(True)
    fig.suptitle("Discovered Knowledge: Coverage and Cluster Structure", fontsize=17, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    save_figure(fig, output_dir, "figure_4_5_4_discovered_knowledge_overview")
    plt.close(fig)


def eligible_training_rows(manifest_path: Path) -> list[dict]:
    allowed_categories = set(CATEGORY_ORDER)
    excluded_flags = {"listing_multiple_variants", "possible_negation_review"}
    records = []
    with manifest_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if (
                row["split"] == "train"
                and row["image_status"] == "ok"
                and row["category"] in allowed_categories
                and not excluded_flags.intersection(row["flags"])
            ):
                records.append(row)
    return records


def candidate_support(rows: list[dict]) -> pd.DataFrame:
    records = []
    for label, family, patterns in CANDIDATES:
        compiled = [re.compile(pattern, flags=re.IGNORECASE) for pattern in patterns]
        support = sum(
            any(pattern.search(row["title_raw"].lower()) for pattern in compiled)
            for row in rows
        )
        records.append({"candidate": label, "family": family, "support": support})
    return pd.DataFrame(records).sort_values("support", ascending=True)


def plot_novel_candidates(support: pd.DataFrame, output_dir: Path) -> None:
    colors = [CANDIDATE_COLORS[family] for family in support["family"]]
    fig, ax = plt.subplots(figsize=(12.5, 9.5))
    positions = np.arange(len(support))
    bars = ax.barh(positions, support["support"], color=colors)
    ax.set_yticks(positions, support["candidate"])
    ax.set_xlabel("Training documents containing the candidate")
    ax.set_title("Candidate Attributes Discovered Beyond the Seed Schema", fontweight="bold", pad=14)
    ax.grid(axis="x", alpha=0.25)
    ax.set_axisbelow(True)
    ax.set_xlim(0, support["support"].max() * 1.14)
    for bar, value in zip(bars, support["support"]):
        ax.text(bar.get_width() + 6, bar.get_y() + bar.get_height() / 2, str(value), va="center")
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=color)
        for color in CANDIDATE_COLORS.values()
    ]
    ax.legend(handles, list(CANDIDATE_COLORS), title="Proposed taxonomy family", frameon=False, loc="lower right")
    fig.tight_layout()
    save_figure(fig, output_dir, "figure_4_5_5_novel_attribute_candidates")
    plt.close(fig)


def cosine(vector_a: np.ndarray, vector_b: np.ndarray) -> float:
    denominator = float(np.linalg.norm(vector_a) * np.linalg.norm(vector_b))
    return float(np.dot(vector_a, vector_b) / max(denominator, 1e-12))


def coherence_results(model_root: Path) -> pd.DataFrame:
    records = []
    archives: dict[str, dict[str, np.ndarray]] = {}
    for category, first, second, label in COHERENCE_PAIRS:
        if category not in archives:
            archive = np.load(model_root / category / "attribute_representations.npz")
            archives[category] = {key: archive[key] for key in archive.files}
        archive = archives[category]
        lookup = {token: index for index, token in enumerate(archive["vocab"])}
        if first not in lookup or second not in lookup:
            raise ValueError(f"Missing coherence pair for {category}: {first}, {second}")
        first_index, second_index = lookup[first], lookup[second]
        records.append(
            {
                "pair": label,
                "spatial": cosine(archive["spatial"][first_index], archive["spatial"][second_index]),
                "semantic": cosine(archive["semantic"][first_index], archive["semantic"][second_index]),
            }
        )
    return pd.DataFrame(records).sort_values("spatial", ascending=True)


def plot_spatial_semantic_coherence(results: pd.DataFrame, output_dir: Path) -> None:
    positions = np.arange(len(results))
    height = 0.36
    fig, ax = plt.subplots(figsize=(12.5, 8.5))
    ax.barh(positions + height / 2, results["spatial"], height, color="#5b8db8", label="Spatial-map cosine")
    ax.barh(positions - height / 2, results["semantic"], height, color="#d9a441", label="Semantic cosine")
    ax.set_yticks(positions, results["pair"])
    ax.set_xlim(0, 1.04)
    ax.set_xlabel("Cosine similarity")
    ax.set_title("Spatial and Semantic Coherence of Selected Concept Pairs", fontweight="bold", pad=14)
    ax.grid(axis="x", alpha=0.25)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower right")
    for y, spatial, semantic in zip(positions, results["spatial"], results["semantic"]):
        ax.text(spatial + 0.008, y + height / 2, f"{spatial:.3f}", va="center", fontsize=8)
        ax.text(semantic + 0.008, y - height / 2, f"{semantic:.3f}", va="center", fontsize=8)
    fig.tight_layout()
    save_figure(fig, output_dir, "figure_4_5_6_spatial_semantic_coherence")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("outputs/prepared/manifest.jsonl"))
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("outputs/figures/spatial_concepts/3_7_1_category_summary.csv"),
    )
    parser.add_argument("--model-root", type=Path, default=Path("models/local_resnet18"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/figures/evaluation"))
    args = parser.parse_args()

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    summary = load_discovery_summary(args.summary, args.model_root)
    plot_discovery_overview(summary, args.output_dir)
    support = candidate_support(eligible_training_rows(args.manifest))
    plot_novel_candidates(support, args.output_dir)
    plot_spatial_semantic_coherence(coherence_results(args.model_root), args.output_dir)
    print(f"Saved discovered-knowledge figures to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
