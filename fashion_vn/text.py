"""Conservative, auditable normalization; no automatic accent restoration."""
import re
import unicodedata

# Set is both a routed product category and an optional schema attribute.  The
# ao-dai aliases are deliberately specific so that "áo dài tay" (long-sleeve
# top) is not misrouted as a traditional ao-dai outfit.
SET_TYPE_ALIASES = {
    'gym_set': [
        'bộ tập gym', 'set tập gym', 'bộ đồ tập gym', 'set gym',
        'bộ tập yoga', 'set tập yoga', 'bộ đồ tập', 'set đồ tập',
    ],
    'sports_set': [
        'bộ thể thao', 'bộ đồ thể thao', 'quần áo thể thao',
        'quần áo bóng đá', 'bộ bóng đá', 'bộ đá bóng',
    ],
    'ao_dai': [
        'bộ áo dài', 'set áo dài', 'sét áo dài', 'áo dài truyền thống',
        'áo dài cách tân', 'áo dài tết', 'áo dài cưới', 'áo dài kèm quần',
        'áo dài phối quần', 'áo dài và quần', 'áo dài việt nam',
        'áo dài ngũ thân', 'áo dài bưng quả', 'áo dài cô dâu',
        'áo dài chú rể', 'áo dài nữ', 'áo dài nam', 'áo dài bé',
        'áo dài trẻ em',
    ],
    'casual_set': [
        'bộ quần áo', 'bộ đồ', 'set đồ', 'sét đồ', 'đồ bộ', 'set áo',
    ],
}

# Seed terminology is an adaptation for Vietnamese, not discovered ground truth.
LEXICON = {
    'color': {
        'đen': ['đen', 'black'], 'trắng': ['trắng', 'white'],
        'đỏ': ['đỏ', 'red'], 'hồng': ['hồng', 'pink'],
        'xanh_dương': ['xanh dương', 'xanh nước biển', 'blue'],
        'xanh_lá': ['xanh lá cây', 'xanh lá', 'green'],
        'xanh_navy': ['xanh navy', 'xanh than', 'navy'],
        'vàng': ['vàng', 'yellow'], 'tím': ['tím', 'purple'],
        'nâu': ['nâu', 'brown'], 'xám': ['xám', 'màu ghi', 'grey', 'gray'],
        'be': ['màu be', 'beige'], 'kem': ['màu kem'],
    },
    'sleeve': {
        'tay_dài': ['tay dài', 'dài tay', 'long sleeve'],
        'tay_ngắn': ['tay ngắn', 'ngắn tay', 'short sleeve'],
        'tay_lỡ': ['tay lỡ', 'tay lửng'],
        'không_tay': ['không tay', 'sát nách', 'sleeveless'],
        'tay_phồng': ['tay phồng', 'tay bồng'],
        'tay_loe': ['tay loe'], 'tay_raglan': ['tay raglan', 'raglan'],
    },
    'neckline': {
        'cổ_tròn': ['cổ tròn', 'round neck'],
        'cổ_v': ['cổ chữ v', 'cổ v', 'v neck'],
        'cổ_vuông': ['cổ vuông'], 'cổ_lọ': ['cổ lọ'],
        'cổ_yếm': ['cổ yếm'], 'cổ_đổ': ['cổ đổ'],
        'cổ_bẻ': ['cổ bẻ'], 'trễ_vai': ['trễ vai', 'off shoulder'],
        'hai_dây': ['hai dây', '2 dây'], 'một_vai': ['một vai', 'lệch vai'],
    },
    'fit': {
        'rộng': ['form rộng', 'phom rộng', 'dáng rộng', 'oversize', 'over size', 'oversized'],
        'ôm': ['dáng ôm', 'form ôm', 'bodycon', 'slim fit', 'skinny'],
        'suông': ['dáng suông', 'form suông'],
    },
    'pattern': {
        'trơn': ['màu trơn', 'trơn'], 'kẻ_sọc': ['kẻ sọc', 'kẻ dọc', 'sọc dọc', 'kẻ ngang'],
        'caro': ['ca rô', 'caro', 'kẻ ô'], 'chấm_bi': ['chấm bi'],
        'hoa': ['hoa nhí', 'họa tiết hoa', 'hoạ tiết hoa', 'in hoa'],
        'in_hình': ['in hình', 'hình in'], 'loang': ['wash loang', 'loang', 'tie dye'],
        'da_báo': ['da báo'],
    },
    'material_claim': {
        'cotton': ['cotton', 'cottonn', 'coton'], 'denim': ['denim', 'vải jean', 'vải jeans'],
        'lụa': ['lụa', 'silk'], 'voan': ['voan', 'chiffon'],
        'len': ['len'], 'ren': ['ren', 'lace'], 'nhung': ['nhung', 'velvet'],
        'linen': ['linen', 'vải lanh'], 'kaki': ['kaki', 'khaki'],
        'nỉ': ['nỉ'], 'da_lộn': ['da lộn'], 'canvas': ['canvas'],
    },
    'length': {
        'maxi': ['maxi'], 'midi': ['midi'], 'mini': ['mini'],
        'croptop': ['croptop', 'crop top'],
    },
    'pant_cut': {
        'ống_rộng': ['ống rộng'], 'ống_suông': ['ống suông'],
        'ống_loe': ['ống loe'], 'ống_đứng': ['ống đứng'], 'ống_bó': ['ống bó'],
    },
    'waist': {'cạp_cao': ['cạp cao', 'lưng cao', 'eo cao'], 'cạp_thấp': ['cạp thấp', 'lưng thấp']},
    'set_type': SET_TYPE_ALIASES,
}

STOP = set('nam nữ unisex cho và của với có là hàng shop store cao cấp đẹp mới hot sale freeship miễn phí giao siêu cực chất liệu thời trang phong cách thiết kế sản phẩm chính hãng mua giá rẻ mềm mại thoáng mát co giãn dễ phối đồ đi mặc mùa hè đông thu xuân mẫu màu size bigsize freesize local brand'.split())

VISUAL_GROUPS = {
    'top': {'color', 'sleeve', 'neckline', 'fit', 'pattern', 'length'},
    'dress': {'color', 'sleeve', 'neckline', 'fit', 'pattern', 'length', 'waist'},
    'jacket': {'color', 'sleeve', 'neckline', 'fit', 'pattern', 'length'},
    'pants': {'color', 'fit', 'pattern', 'pant_cut', 'waist'},
    'skirt': {'color', 'fit', 'pattern', 'length', 'waist'},
    'set': {
        'color', 'sleeve', 'neckline', 'fit', 'pattern', 'length',
        'pant_cut', 'waist', 'set_type',
    },
    'bag': {'color', 'pattern'}, 'hat': {'color', 'pattern'}, 'shoe': {'color', 'pattern'},
}

def normalize(text):
    text = unicodedata.normalize('NFKC', str(text or '')).lower()
    text = re.sub(r'[_/–—-]+', ' ', text)
    text = re.sub(r'[^\w\s%]', ' ', text, flags=re.UNICODE)
    return re.sub(r'\s+', ' ', text).strip()

def contains(text, phrase):
    return bool(re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', text))

def extract(title):
    normalized = normalize(title)
    # Longest phrases win, so xanh navy cannot also become a generic xanh.
    aliases = sorted([(normalize(a), concept, value)
                      for concept, values in LEXICON.items()
                      for value, forms in values.items() for a in forms],
                     key=lambda x: len(x[0]), reverse=True)
    occupied, matches = set(), []
    for alias, concept, value in aliases:
        for m in re.finditer(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', normalized):
            span = set(range(m.start(), m.end()))
            if occupied & span:
                continue
            occupied |= span
            matches.append({'concept': concept, 'value': value, 'evidence': m.group(),
                            'start': m.start(), 'end': m.end(), 'source': 'title_rule'})
    tokens, end = [], 0
    for m in sorted(matches, key=lambda m: m['start']):
        tokens.extend(normalized[end:m['start']].split())
        tokens.append(m['value'])
        end = m['end']
    tokens.extend(normalized[end:].split())
    tokens = [t for t in tokens if t not in STOP and not any(c.isdigit() for c in t) and len(t) > 1]
    attrs = {}
    for m in matches:
        attrs.setdefault(m['concept'], set()).add(m['value'])
    attrs = {k: sorted(v) for k, v in attrs.items()}
    flags = []
    if re.search(r'\b\d+\s*màu\b|nhiều màu|đủ màu|nhiều mẫu|nhiều kiểu', normalized):
        flags.append('listing_multiple_variants')
    if len(attrs.get('color', [])) > 1:
        flags.append('multiple_color_mentions')
    if contains(normalized, 'xanh') and not any(v.startswith('xanh_') for v in attrs.get('color', [])):
        flags.append('ambiguous_xanh')
    if any(v in normalized for v in ['không phải', 'không có', 'không in', 'không cotton']):
        flags.append('possible_negation_review')
    return normalized, tokens, attrs, matches, flags

def category_hint(title):
    t = normalize(title)
    if contains(t, 'áo dài'):
        if any(contains(t, phrase) for phrase in ['không kèm quần', 'không kèm theo quần']):
            return 'top'
        if any(contains(t, phrase) for phrase in [
            'quần lụa áo dài', 'quần mặc áo dài', 'quần áo dài',
            'mặc bên trong áo dài', 'mặc với áo dài',
        ]):
            return 'pants'
    rules = [
        ('fabric', ['vải may', 'vải kate', 'vải khúc', 'vải mét']),
        ('set', [alias for aliases in SET_TYPE_ALIASES.values() for alias in aliases]),
        ('bag', ['túi xách', 'túi đeo', 'túi vải', 'túi tote', 'balo', 'ba lô']),
        ('hat', ['mũ lưỡi trai', 'mũ bucket', 'nón lưỡi trai', 'mũ len', 'nón bucket']),
        ('shoe', ['giày', 'dép', 'sandal']),
        ('skirt', ['chân váy', 'chân zuýp']),
        ('jacket', ['áo khoác', 'măng tô', 'blazer', 'cardigan', 'jacket']),
        ('dress', ['đầm', 'váy']), ('pants', ['quần']),
        ('top', ['áo', 'shirt', 'hoodie']),
        ('hat', ['mũ', 'nón']),
    ]
    for cat, phrases in rules:
        if any(contains(t, p) for p in phrases):
            return cat
    return 'unknown'
