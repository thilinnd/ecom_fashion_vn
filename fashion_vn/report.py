"""Create a concise Vietnamese audit/report from real run artifacts."""
import collections
import json
from pathlib import Path
import statistics
from .prepare import read_rows, write_json

def main():
    prepared = Path('outputs/prepared')
    rows = read_rows(prepared/'manifest.jsonl')
    audit = json.loads((prepared/'audit.json').read_text(encoding='utf-8'))
    referenced = {Path(r['image_path']).resolve() for r in rows}
    available = {p.resolve() for p in Path('data/shopee_img').glob('*') if p.is_file()}
    sizes = [r['image_size'] for r in rows if r['image_size']]
    lengths = [len(r['title_normalized'].split()) for r in rows]
    profile = dict(n_referenced_images=len(referenced), n_files_in_image_directory=len(available),
                   n_unreferenced_files=len(available-referenced),
                   unique_image_sha256=len({r['image_sha256'] for r in rows if r['image_sha256']}),
                   min_title_words=min(lengths), median_title_words=statistics.median(lengths),
                   max_title_words=max(lengths),
                   n_images_short_side_under_224=sum(min(s)<224 for s in sizes),
                   median_width=statistics.median(s[0] for s in sizes),
                   median_height=statistics.median(s[1] for s in sizes))
    write_json(prepared/'dataset_profile.json', profile)
    lines = ['# Báo cáo dữ liệu thời trang địa phương', '',
             'Số liệu dưới đây được tính trực tiếp từ Excel và ảnh trong workspace.', '',
             f'- Sản phẩm: **{len(rows):,}**.',
             f'- Ảnh đọc được: **{audit["image_status"].get("ok",0):,}**.',
             f'- Số ảnh có nội dung byte khác nhau: **{profile["unique_image_sha256"]:,}**.',
             f'- File trong thư mục ảnh chưa được Excel tham chiếu: **{profile["n_unreferenced_files"]:,}**; chưa đưa vào tập sản phẩm.',
             f'- Tiêu đề trùng nguyên văn (số dòng dư): **{audit["rows_beyond_unique_raw_titles"]}**.',
             f'- Nhóm chống rò rỉ sau gom tiêu đề/ảnh trùng: **{audit["n_duplicate_groups"]:,}**.',
             f'- Sản phẩm có ít nhất một nhãn yếu từ title: **{audit["products_with_title_attributes"]:,}**.',
             f'- Trung vị độ dài title: **{profile["median_title_words"]} từ cách nhau bằng khoảng trắng**.',
             f'- Trung vị kích thước ảnh: **{profile["median_width"]} × {profile["median_height"]} px**.',
             '', '| Split | Sản phẩm |', '|---|---:|']
    lines += [f'| {k} | {v:,} |' for k,v in audit['splits'].items()]
    lines += ['', 'Phân loại dưới đây được suy ra từ tiêu đề bằng quy tắc, chưa có gold xác nhận.',
              '', '| Nhóm gợi ý | Sản phẩm |', '|---|---:|']
    lines += [f'| {k} | {v:,} |' for k,v in sorted(audit['category_hints_unverified'].items())]
    lines += ['', '## Trạng thái mô hình', '']
    trained = Path('models/local_resnet18/run_summary.json')
    if trained.exists():
        models = json.loads(trained.read_text(encoding='utf-8'))
        lines += ['Baseline đã học trên đặc trưng **ResNet18 ImageNet đóng băng**, theo cơ chế VSE → AAM + Word2vec → K-means → concept heads.',
                  'Đây là triển khai điều chỉnh từ bài báo; chưa phải lượt Inception V3 fine-tune toàn mạng.',
                  '', '| Nhóm | Train hợp lệ | Val hợp lệ | Từ vựng | Cụm | Head | Trạng thái |', '|---|---:|---:|---:|---:|---:|---|']
        for cat, s in models.items():
            lines.append(f'| {cat} | {s.get("train",0)} | {s.get("val",0)} | {s.get("vocabulary",s.get("vocab",0))} | {s.get("concepts",0)} | {s.get("heads",0)} | {s["status"]} |')
    else:
        lines.append('Chưa có run_summary của lượt huấn luyện hoàn tất. Không suy diễn kết quả mô hình từ nhãn title.')
    predictions = Path('outputs/predictions/summary.json')
    if predictions.exists():
        s = json.loads(predictions.read_text(encoding='utf-8'))
        lines += ['', f'- Đã xuất {s["n_products"]:,} sản phẩm.',
                  f'- Nhánh tạo file chính: **{s.get("head_type", "discovered")}**. Nếu là schema, đây là nhóm Việt hóa thủ công trên VSE đã học, không phải cụm tự động.',
                  f'- {s["products_with_image_candidates"]:,} sản phẩm có ít nhất một giả thuyết thuộc tính ảnh vượt ngưỡng heuristic.',
                  '- Tất cả điểm số chưa được hiệu chỉnh; nhãn tự động chưa được chuyên gia xác nhận.',
                  '- Độ phủ tự động không phải độ chính xác.']
    discovered = Path('outputs/predictions_discovered/summary.json')
    if discovered.exists():
        d = json.loads(discovered.read_text(encoding='utf-8'))
        lines += ['', f'- Nhánh cụm tự động có {d["products_with_image_candidates"]:,} sản phẩm có giả thuyết thuộc tính chuẩn hóa vượt ngưỡng.',
                  '- Hai nhánh khác số lớp và chưa hiệu chỉnh score; không suy ra nhánh nào chính xác hơn chỉ từ số sản phẩm được gán nhãn.']
    lines += ['', '## Những vấn đề cần ưu tiên trước khi công bố', '',
              '1. Kiểm tra ảnh ghép và nhiều sản phẩm: mẫu ảnh 00001 ghép nhiều áo màu khác nhau; 07925 có người mẫu và các váy treo phía sau. Chưa có detector hay chọn sản phẩm đích.',
              '2. Title có nhiều biến thể, sai chính tả và quảng cáo. Giữ nguyên title gốc, lưu evidence và tách chất liệu do người bán khai báo.',
              '3. Rà soát category_hint, vocabulary_review và concept_review; không coi các cụm máy tạo là taxonomy chuẩn.',
              '4. Điền phiếu mù validation/test và phân xử nhãn trước khi báo F1/mAP. Hiện **chưa có số đo độ chính xác thuộc tính dựa trên gold**.',
              '5. Kiểm tra near-duplicate và cùng shop nếu thu thập thêm được metadata; quy tắc split hiện tại chưa giải quyết toàn bộ domain leakage.',
              '', 'Hướng dẫn phương pháp, lệnh chạy và đánh giá: [README](../../README.md).']
    (prepared/'DATA_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(profile, ensure_ascii=True))

if __name__ == '__main__':
    main()
