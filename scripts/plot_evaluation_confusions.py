"""Create report figures for category and schema-attribute confusion analysis."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


CATEGORY_ROWS = [
    "bag", "dress", "fabric", "hat", "jacket", "other",
    "pants", "set", "skirt", "top", "unknown",
]
CATEGORY_COLUMNS = [
    "bag", "dress", "fabric", "hat", "jacket",
    "pants", "set", "skirt", "top", "unknown",
]

ATTRIBUTE_SPECS = {
    "fit": {
        "gold": ["rộng", "ôm", "suông"],
        "predicted": ["rộng", "ôm", "suông", "Not present"],
        "title": "(a) Fit",
    },
    "length": {
        "gold": ["maxi", "midi", "mini", "croptop"],
        "predicted": ["maxi", "midi", "mini", "croptop", "Not present"],
        "title": "(b) Length",
    },
    "sleeve": {
        "gold": ["tay_dài", "tay_ngắn", "tay_lỡ", "không_tay"],
        "predicted": [
            "tay_dài", "tay_ngắn", "tay_lỡ", "không_tay",
            "tay_phồng", "tay_loe", "Multiple other labels", "Not present",
        ],
        "title": "(c) Sleeve",
    },
}


def split_labels(value: object) -> set[str]:
    if pd.isna(value) or not str(value).strip():
        return set()
    return {item.strip() for item in str(value).split(";") if item.strip()}


def save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_dir / f"{stem}.png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(output_dir / f"{stem}.svg", bbox_inches="tight", facecolor="white")


def draw_count_heatmap(
    ax: plt.Axes,
    matrix: np.ndarray,
    row_labels: list[str],
    column_labels: list[str],
    title: str,
    colorbar: bool = True,
) -> None:
    """Color by row percentage while annotating each cell with count and percent."""
    matrix = np.asarray(matrix, dtype=int)
    totals = matrix.sum(axis=1, keepdims=True)
    shares = np.divide(
        matrix,
        totals,
        out=np.zeros_like(matrix, dtype=float),
        where=totals != 0,
    )
    image = ax.imshow(shares, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(column_labels)), column_labels, rotation=40, ha="right")
    ax.set_yticks(range(len(row_labels)), row_labels)
    ax.set_xlabel("Predicted Labels")
    ax.set_ylabel("Gold Labels")
    ax.set_title(title, fontweight="bold", pad=12)

    for row in range(matrix.shape[0]):
        for column in range(matrix.shape[1]):
            count = matrix[row, column]
            share = shares[row, column]
            color = "white" if share >= 0.48 else "#17202a"
            ax.text(
                column,
                row,
                f"{count}\n({share:.0%})",
                ha="center",
                va="center",
                fontsize=8,
                color=color,
            )

    ax.set_xticks(np.arange(-0.5, len(column_labels), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(row_labels), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.2)
    ax.tick_params(which="minor", bottom=False, left=False)
    if colorbar:
        bar = ax.figure.colorbar(image, ax=ax, fraction=0.035, pad=0.025)
        bar.set_label("Proportion by Row")


def build_category_matrix(path: Path) -> np.ndarray:
    data = pd.read_csv(path, encoding="utf-8-sig")
    pivot = data.pivot_table(
        index="category_gold",
        columns="category_hint",
        values="count",
        aggfunc="sum",
        fill_value=0,
    )
    pivot = pivot.reindex(index=CATEGORY_ROWS, columns=CATEGORY_COLUMNS, fill_value=0)
    return pivot.to_numpy(dtype=int)


def build_attribute_matrix(
    rows: pd.DataFrame,
    group: str,
    gold_labels: list[str],
    predicted_labels: list[str],
) -> np.ndarray:
    matrix = np.zeros((len(gold_labels), len(predicted_labels)), dtype=int)
    gold_index = {label: index for index, label in enumerate(gold_labels)}
    predicted_index = {label: index for index, label in enumerate(predicted_labels)}
    group_rows = rows.loc[rows["group"] == group]

    for record in group_rows.itertuples(index=False):
        gold = split_labels(record.gold)
        predicted = split_labels(record.predicted)
        for gold_label in gold.intersection(gold_index):
            row = gold_index[gold_label]
            if not predicted:
                column_label = "Not present"
            elif gold_label in predicted:
                # The gold attribute is present, even when an extra label was emitted.
                column_label = gold_label
            elif len(predicted) == 1 and next(iter(predicted)) in predicted_index:
                column_label = next(iter(predicted))
            elif "Multiple other labels" in predicted_index:
                column_label = "Multiple other labels"
            else:
                raise ValueError(
                    f"Unexpected {group} prediction for {record.product_id}: {predicted}"
                )
            matrix[row, predicted_index[column_label]] += 1

    return matrix


def plot_category_confusion(category_csv: Path, output_dir: Path) -> None:
    matrix = build_category_matrix(category_csv)
    fig, ax = plt.subplots(figsize=(14, 9))
    draw_count_heatmap(
        ax,
        matrix,
        CATEGORY_ROWS,
        CATEGORY_COLUMNS,
        "Category Confusion Matrix",
    )
    ax.text(
        0,
        -0.16,
        "Colors represent the proportion by row; each cell shows the count and proportion within the gold category.",
        transform=ax.transAxes,
        fontsize=9,
    )
    fig.subplots_adjust(bottom=0.21)
    save_figure(fig, output_dir, "figure_4_5_1_category_confusion_matrix")
    plt.close(fig)


def plot_attribute_confusions(group_predictions_csv: Path, output_dir: Path) -> None:
    rows = pd.read_csv(group_predictions_csv, encoding="utf-8-sig", keep_default_na=False)
    matrices = {
        group: build_attribute_matrix(rows, group, spec["gold"], spec["predicted"])
        for group, spec in ATTRIBUTE_SPECS.items()
    }

    # Stack the panels so the figure remains readable on a portrait thesis page.
    fig, axes = plt.subplots(3, 1, figsize=(14, 17))
    for ax, (group, spec) in zip(axes, ATTRIBUTE_SPECS.items()):
        draw_count_heatmap(
            ax,
            matrices[group],
            spec["gold"],
            spec["predicted"],
            spec["title"],
            colorbar=False,
        )
    fig.suptitle(
        "Attribute Confusion Matrices of the Schema Branch",
        fontsize=17,
        fontweight="bold",
        y=1.02,
    )
    fig.text(
        0.02,
        0.005,
        "Diagonal cell: 'gold attribute' is present in the prediction. 'Not present': abstention. "
        "Colors and percentages are normalized by row.",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0.025, 1, 0.985), h_pad=2.2)
    save_figure(fig, output_dir, "figure_4_5_2_schema_attribute_confusion_matrices")
    plt.close(fig)


def plot_top_confusion_pairs(confusions_csv: Path, output_dir: Path, top_n: int) -> None:
    data = pd.read_csv(confusions_csv, encoding="utf-8-sig")
    data = data.sort_values(["count", "count_over_gold_support"], ascending=False).head(top_n)
    labels = [
        f"{row.group}: {row.gold_attribute} → {row.predicted_attribute}"
        for row in data.itertuples(index=False)
    ]
    counts = data["count"].to_numpy()
    rates = data["count_over_gold_support"].to_numpy()

    fig, ax = plt.subplots(figsize=(12, 8))
    positions = np.arange(len(data))
    bars = ax.barh(positions, counts, color="#d97757")
    ax.set_yticks(positions, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Number of Cases")
    ax.set_title("Top Attribute Confusion Pairs", fontweight="bold", pad=12)
    ax.grid(axis="x", alpha=0.25)
    ax.set_axisbelow(True)
    for bar, count, rate in zip(bars, counts, rates):
        ax.text(
            bar.get_width() + 0.25,
            bar.get_y() + bar.get_height() / 2,
            f"{int(count)} ({rate:.1%} gold samples)",
            va="center",
            fontsize=9,
        )
    ax.set_xlim(0, max(counts) * 1.5)
    fig.tight_layout()
    save_figure(fig, output_dir, "figure_4_5_3_top_attribute_confusions")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-dir", type=Path, default=Path("outputs/evaluation_set_v2"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/figures/evaluation"),
    )
    parser.add_argument("--top-n", type=int, default=15)
    args = parser.parse_args()

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    plot_category_confusion(args.evaluation_dir / "category_confusion.csv", args.output_dir)
    plot_attribute_confusions(
        args.evaluation_dir / "schema_visual_scope_group_predictions.csv",
        args.output_dir,
    )
    plot_top_confusion_pairs(
        args.evaluation_dir / "schema_visual_scope_attribute_confusions.csv",
        args.output_dir,
        args.top_n,
    )
    print(f"Saved confusion figures to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
