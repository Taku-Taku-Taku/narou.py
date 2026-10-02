"""なろう→Kindle縦書きEPUB変換ツール"""

import argparse
import re
import sys

import requests
from tqdm import tqdm

from scraper import NarouScraper
from parser import RubyParser
from epub_generator import EpubGenerator
from cache import CacheManager

IMG_PATTERN = re.compile(r'<img[^>]+src="([^"]+)"')

# ncode単体、または作品・各話のURL (https://ncode.syosetu.com/n1234ab/ など)
NCODE_PATTERN = re.compile(r"(?:^|/)(n\d{4}[a-z]+)(?:/|$)", re.IGNORECASE)


def extract_ncode(text: str) -> str | None:
    """ncodeまたは作品URLからncodeを取り出す（小文字に正規化）"""
    m = NCODE_PATTERN.search(text.strip())
    return m.group(1).lower() if m else None


def parse_args():
    p = argparse.ArgumentParser(
        description="小説家になろうの作品をKindle向け縦書きEPUBに変換"
    )
    p.add_argument(
        "ncode",
        nargs="?",
        help="作品のNコードまたはURL (例: n1234ab, https://ncode.syosetu.com/n1234ab/)",
    )
    p.add_argument("--start", type=int, default=None, help="開始話数")
    p.add_argument("--end", type=int, default=None, help="終了話数")
    p.add_argument("--no-cache", action="store_true", help="キャッシュを使用しない")
    p.add_argument("--output", "-o", default="output", help="出力ディレクトリ")
    p.add_argument(
        "--clear-cache",
        action="store_true",
        help="キャッシュを削除（ncodeを指定すると該当作品のみ削除）",
    )
    p.add_argument(
        "--image-size",
        choices=["small", "medium", "large"],
        default=None,
        help="画像の最大解像度 (small:6型, medium:7型, large:10型)。未指定時はリサイズなし",
    )
    return p.parse_args()


def main():
    args = parse_args()

    ncode = None
    if args.ncode:
        ncode = extract_ncode(args.ncode)
        if ncode is None:
            print(
                f"エラー: ncodeまたは作品URLとして認識できません: {args.ncode}",
                file=sys.stderr,
            )
            sys.exit(1)

    # キャッシュクリア
    if args.clear_cache:
        cache = CacheManager()
        cache.clear(ncode)
        if ncode:
            print(f"キャッシュを削除しました: {ncode}")
        else:
            print("全キャッシュを削除しました")
            return

    if not ncode:
        print("エラー: ncodeを指定してください", file=sys.stderr)
        sys.exit(1)

    cache = CacheManager(enabled=not args.no_cache)
    scraper = NarouScraper(cache=cache)
    parser = RubyParser()
    image_presets = {
        "small":  (1072, 1448),  # 6型 (Kindle等)
        "medium": (1236, 1648),  # 7型 (Kindle Paperwhite等)
        "large":  (1860, 2480),  # 10型 (Kindle Scribe等)
    }
    img_w, img_h = image_presets.get(args.image_size, (None, None))
    generator = EpubGenerator(
        output_dir=args.output,
        image_max_width=img_w,
        image_max_height=img_h,
    )

    # 1. メタデータ取得
    print(f"メタデータ取得中: {ncode}")
    metadata = scraper.fetch_metadata(ncode)
    if not metadata:
        print(f"エラー: 作品 {ncode} が見つかりません", file=sys.stderr)
        sys.exit(1)
    print(f"  タイトル: {metadata['title']}")
    print(f"  著者: {metadata['writer']}")
    print(f"  総話数: {metadata['general_all_no']}")

    # 2. 目次・章構造取得
    print("目次取得中...")
    toc = scraper.fetch_toc(ncode, total_episodes=metadata["general_all_no"])

    # 3. 話数範囲フィルタ
    episodes = toc["episodes"]
    if args.start is not None:
        episodes = [e for e in episodes if e["number"] >= args.start]
    if args.end is not None:
        episodes = [e for e in episodes if e["number"] <= args.end]
    if episodes:
        print(f"  対象話数: {len(episodes)}話 (第{episodes[0]['number']}話〜第{episodes[-1]['number']}話)")
    else:
        print("  対象話数なし")
        return

    # 4. 本文取得 + ルビ変換 + 画像ダウンロード
    for ep in tqdm(episodes, desc="本文取得中", unit="話"):
        body_html = scraper.fetch_episode(ncode, ep["number"])
        ep["body"] = parser.convert(body_html)
        # 挿絵を検出・ダウンロード
        ep["images"] = []
        # 同じ画像が複数回出てきても1回だけ取得する
        for src in dict.fromkeys(IMG_PATTERN.findall(ep["body"])):
            if src.startswith("//"):
                # プロトコル相対URL → https に補完
                url = "https:" + src
            elif src.startswith("http"):
                url = src
            else:
                continue
            try:
                data = scraper.fetch_image(ncode, url)
            except requests.RequestException as e:
                # 削除済み画像などは挿絵を外して続行
                tqdm.write(f"  警告: 第{ep['number']}話の挿絵を取得できませんでした: {url} ({e})")
                ep["body"] = re.sub(
                    rf'<img[^>]+src="{re.escape(src)}"[^>]*>', "", ep["body"]
                )
                continue
            ep["images"].append({"src": src, "data": data})

    # 5. 章分割 + EPUB生成
    volumes = generator.split_into_volumes(toc["chapters"], episodes)
    for vol in tqdm(volumes, desc="EPUB生成中", unit="巻"):
        path = generator.generate(metadata, vol)
        tqdm.write(f"  生成: {path}")

    print("完了")


if __name__ == "__main__":
    main()
