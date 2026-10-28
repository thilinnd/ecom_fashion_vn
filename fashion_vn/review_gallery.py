"""Create a local, blind image gallery corresponding to the annotation CSV."""
import csv
import html
import os
from pathlib import Path
from urllib.parse import quote

def main():
    root = Path('outputs/prepared').resolve()
    with (root/'annotation_blind.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    cards = []
    for r in rows:
        relative = Path(os.path.relpath(r['image_path'], root)).as_posix()
        cards.append('<article data-split="' + html.escape(r['split']) + '"><h3>ID ' +
                     html.escape(r['product_id']) + ' · ' + html.escape(r['split']) + '</h3><img loading="lazy" src="' +
                     quote(relative, safe='/.:') + '" alt="Ảnh sản phẩm ' + html.escape(r['product_id']) +
                     '"><p>Điền nhãn vào dòng có ID tương ứng trong annotation_blind.csv.</p></article>')
    document = '''<!doctype html><html lang="vi"><meta charset="utf-8"><title>Phiếu ảnh đánh giá mù</title>
<style>body{font-family:system-ui;background:#f5f5f5;color:#202020;margin:24px}header{max-width:1000px}
main{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}article{background:white;padding:16px;border-radius:8px}
img{width:100%;height:280px;object-fit:contain}p{font-size:14px;line-height:1.5}select{padding:8px;margin-bottom:16px}</style>
<header><h1>Đánh giá ảnh sản phẩm</h1><p>Không hiển thị title, loại do máy gợi ý hoặc dự đoán thuộc tính.
Kiểm tra ảnh ghép, sản phẩm đích và khả năng nhìn thấy thuộc tính trước khi gán nhãn.
Không xác định được thì ghi unknown/not_visible; không suy diễn chất liệu từ ảnh.</p>
<p>Mẫu lấy phân tầng theo loại gợi ý, tối đa 200 ảnh mỗi split; đây không phải mẫu ngẫu nhiên đều của toàn bộ dữ liệu.
Khi báo số đo tổng thể, cân nhắc trọng số lấy mẫu và báo riêng theo loại.</p>
<select aria-label="Chọn split" onchange="document.querySelectorAll('article').forEach(x=>x.hidden=this.value!=='all'&&x.dataset.split!==this.value)">
<option value="all">Tất cả</option><option value="val">Validation</option><option value="test">Test</option></select></header><main>'''
    (root/'annotation_gallery.html').write_text(document + '\n'.join(cards) + '</main></html>', encoding='utf-8')
    print(f'Created blind gallery for {len(rows)} products.')

if __name__ == '__main__':
    main()
