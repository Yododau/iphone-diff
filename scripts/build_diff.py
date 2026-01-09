import json
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))

# 1) Morimori: trang price list tìm iPhone 17
MORIMORI_URL = "https://www.morimori-kaitori.jp/search?sk=iPhone17&page=1&price-list=true"

# 2) Apple JP: dùng trang mua iPhone (không phải app-store/)
# Bạn có thể thêm/bớt model tùy ý
APPLE_BUY_PAGES = {
    "iPhone 17": "https://www.apple.com/jp/shop/buy-iphone/iphone-17",
    "iPhone 17 Pro": "https://www.apple.com/jp/shop/buy-iphone/iphone-17-pro",
    "iPhone Air": "https://www.apple.com/jp/shop/buy-iphone/iphone-air",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
    )
}


# -------------------------
# Helpers
# -------------------------
def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def parse_yen_values(text: str) -> List[int]:
    """
    Tìm tất cả số dạng '129,800円' trong text.
    """
    vals = []
    for m in re.findall(r"(\d[\d,]*)\s*円", text):
        vals.append(int(m.replace(",", "")))
    return vals


def norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def extract_capacity(model_text: str) -> Optional[str]:
    """
    Cố gắng bắt dung lượng nếu có trong chuỗi (128GB, 256GB, 512GB, 1TB, 2TB).
    """
    m = re.search(r"\b(128GB|256GB|512GB|1TB|2TB)\b", model_text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return None


# -------------------------
# Apple: lấy giá "từ ...円から"
# -------------------------
def scrape_apple_base_prices() -> Dict[str, int]:
    """
    Lấy giá base (giá 'から') cho mỗi model từ trang Apple JP.
    Cách làm an toàn hơn:
    - Tìm các đoạn JSON nhúng trong trang có chứa nhiều giá lớn (>= 50000)
    - Lấy giá nhỏ nhất trong tập giá lớn đó làm "starting price"
    """
    out: Dict[str, int] = {}

    for model, url in APPLE_BUY_PAGES.items():
        html = fetch(url)
        soup = BeautifulSoup(html, "lxml")

        # Lấy text của tất cả <script> để tìm JSON nhúng
        scripts = soup.find_all("script")
        best_candidate: Optional[int] = None

        for sc in scripts:
            s = sc.string
            if not s:
                continue

            # Lấy tất cả số dạng ...円 trong script (thường có)
            yens = parse_yen_values(s)
            if not yens:
                continue

            # Chỉ giữ giá "to" (iPhone thường >= 50000円)
            big = [v for v in yens if v >= 50000]
            if not big:
                continue

            # Giá base thường là giá nhỏ nhất trong các giá lớn
            cand = min(big)

            # Chọn candidate hợp lý nhất (nhỏ nhưng không quá nhỏ)
            if best_candidate is None or cand < best_candidate:
                best_candidate = cand

        # Fallback cuối cùng: nếu không tìm thấy trong script, thử trong toàn HTML
        if best_candidate is None:
            all_yens = parse_yen_values(html)
            big = [v for v in all_yens if v >= 50000]
            if big:
                best_candidate = min(big)

        if best_candidate is not None:
            out[model] = best_candidate

    return out

def scrape_apple_prices_by_capacity() -> Dict[Tuple[str, str], int]:
    out: Dict[Tuple[str, str], int] = {}
    cap_pat = re.compile(r"\b(128GB|256GB|512GB|1TB|2TB)\b", re.IGNORECASE)

    for model, url in APPLE_BUY_PAGES.items():
        html = fetch(url)
        soup = BeautifulSoup(html, "lxml")

        for sc in soup.find_all("script"):
            s = sc.string
            if not s:
                continue

            for m in cap_pat.finditer(s):
                cap = m.group(1).upper()
                start = max(0, m.start() - 600)
                end = min(len(s), m.end() + 600)
                window = s[start:end]

                yens = parse_yen_values(window)
                big = [v for v in yens if v >= 50000]
                if not big:
                    continue

                cand = min(big)
                key = (model, cap)
                if key not in out or cand < out[key]:
                    out[key] = cand

    return out


# -------------------------
# Morimori: lấy giá thu mua "新品"
# -------------------------
def scrape_morimori_new_prices() -> Dict[Tuple[str, str], int]:
    html = fetch(MORIMORI_URL)
    soup = BeautifulSoup(html, "lxml")

    out: Dict[Tuple[str, str], int] = {}

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cols = [norm_spaces(td.get_text(" ")) for td in tr.find_all(["td", "th"])]
            if not cols:
                continue
            row = " ".join(cols)

            if "新品" not in row:
                continue

            cap = extract_capacity(row)
            if not cap:
                continue

            model = None
            if "Pro Max" in row or "ProMax" in row:
                model = "iPhone 17 Pro Max"
            elif "Pro" in row:
                model = "iPhone 17 Pro"
            elif "Air" in row:
                model = "iPhone Air"
            elif "iPhone 17" in row or "iPhone17" in row:
                model = "iPhone 17"

            if not model:
                continue

            yens = parse_yen_values(row)
            if not yens:
                continue

            price = max(yens)
            key = (model, cap)
            out[key] = max(out.get(key, 0), price)

    return out


# -------------------------
# Build output JSON
# -------------------------
def build_diff_rows(
    apple: Dict[Tuple[str, str], int],
    morimori: Dict[Tuple[str, str], int],
) -> List[dict]:
    rows: List[dict] = []

    for (model, cap) in sorted(set(apple.keys()) & set(morimori.keys())):
        diff = morimori[(model, cap)] - apple[(model, cap)]
        rows.append(
            {
                "model": model,
                "capacity": cap,
                "apple_price": apple[(model, cap)],
                "morimori_new_price": morimori[(model, cap)],
                "diff": diff,
            }
        )

    rows.sort(key=lambda x: x["diff"], reverse=True)
    return rows


def main():
    apple = scrape_apple_prices_by_capacity()
    morimori = scrape_morimori_new_prices()
    rows = build_diff_rows(apple, morimori)

    print("Done. rows:", len(rows))
    print("Apple pairs:", len(apple))
    print("Morimori pairs:", len(morimori))

    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    meta = {
        "generated_at_jst": now,
        "sources": {
            "morimori": MORIMORI_URL,
            "apple": APPLE_BUY_PAGES,
        },
        "debug_counts": {
            "apple_models": len(apple),
            "morimori_models": len(morimori),
            "matched_rows": len(rows),
        },
    }

    # ghi ra data/
    with open("data/diff.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    with open("data/meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("Done. rows:", len(rows))
    print("Apple:", apple)
    print("Morimori:", morimori)


if __name__ == "__main__":
    main()
