"""Create 4 x 5 contact sheets from each cluster's multi-term evidence images."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
COLS = 5
ROWS = 4
EXPECTED_IMAGES = COLS * ROWS


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def natural_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def cluster_title(cluster_dir: Path) -> str:
    match = re.match(r"cluster_(\d+)_(.+)", cluster_dir.name)
    if not match:
        return cluster_dir.name.replace("_", " ").title()
    cluster_id, label = match.groups()
    return f"Cluster {int(cluster_id)} — {label.replace('_', ' ').title()}"


def product_caption(image_path: Path) -> str:
    match = re.search(r"product_(\d+)", image_path.stem)
    return f"Product {int(match.group(1))}" if match else image_path.stem


def make_montage(cluster_dir: Path, output_dir: Path) -> Path:
    evidence_dir = cluster_dir / "multi_term_evidence"
    images = sorted(
        (path for path in evidence_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES),
        key=natural_key,
    )
    if len(images) != EXPECTED_IMAGES:
        raise ValueError(
            f"{cluster_dir.name}: expected {EXPECTED_IMAGES} images in {evidence_dir}, found {len(images)}"
        )

    canvas_width = 2500
    header_height = 110
    outer_margin = 30
    gap = 14
    cell_width = (canvas_width - 2 * outer_margin - (COLS - 1) * gap) // COLS
    cell_height = 390
    caption_height = 38
    canvas_height = header_height + 2 * outer_margin + ROWS * cell_height + (ROWS - 1) * gap

    canvas = Image.new("RGB", (canvas_width, canvas_height), "#F4F4F2")
    draw = ImageDraw.Draw(canvas)
    title_font = load_font(42, bold=True)
    caption_font = load_font(24)

    title = cluster_title(cluster_dir)
    title_box = draw.textbbox((0, 0), title, font=title_font)
    title_width = title_box[2] - title_box[0]
    draw.text(((canvas_width - title_width) / 2, 30), title, fill="#202020", font=title_font)

    for index, image_path in enumerate(images):
        row, col = divmod(index, COLS)
        x0 = outer_margin + col * (cell_width + gap)
        y0 = header_height + outer_margin + row * (cell_height + gap)
        x1 = x0 + cell_width
        y1 = y0 + cell_height

        draw.rounded_rectangle((x0, y0, x1, y1), radius=10, fill="white", outline="#D1D1CE", width=2)
        image_box = (x0 + 8, y0 + 8, x1 - 8, y1 - caption_height - 4)
        available_size = (image_box[2] - image_box[0], image_box[3] - image_box[1])

        with Image.open(image_path) as source:
            source = ImageOps.exif_transpose(source).convert("RGB")
            fitted = ImageOps.contain(source, available_size, method=Image.Resampling.LANCZOS)
        image_x = image_box[0] + (available_size[0] - fitted.width) // 2
        image_y = image_box[1] + (available_size[1] - fitted.height) // 2
        canvas.paste(fitted, (image_x, image_y))

        caption = product_caption(image_path)
        caption_box = draw.textbbox((0, 0), caption, font=caption_font)
        caption_width = caption_box[2] - caption_box[0]
        draw.text(
            (x0 + (cell_width - caption_width) / 2, y1 - caption_height + 3),
            caption,
            fill="#333333",
            font=caption_font,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{cluster_dir.name}_multi_term_4x5.png"
    canvas.save(output_path, format="PNG", dpi=(300, 300), optimize=True)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("outputs/cluster_product_images/top_selected_clusters"),
        help="Directory containing cluster_* folders.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory; defaults to <root>/montages.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    output_dir = args.out.resolve() if args.out else root / "montages"
    cluster_dirs = sorted(
        (path for path in root.glob("cluster_*") if path.is_dir() and (path / "multi_term_evidence").is_dir()),
        key=natural_key,
    )
    if not cluster_dirs:
        raise FileNotFoundError(f"No cluster folders with multi_term_evidence found under {root}")

    for cluster_dir in cluster_dirs:
        output_path = make_montage(cluster_dir, output_dir)
        print(output_path)


if __name__ == "__main__":
    main()
