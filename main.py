"""なろう→Kindle縦書きEPUB変換ツール"""

import argparse
import math
import re
import sys
import time

import requests
from tqdm import tqdm

from scraper import (
    DOWNLOAD_INTERVAL,
    DOWNLOAD_WAIT_STEPS,
    STEPS_WAIT_TIME,
    NarouScraper,
)
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


def estimate_remaining(
    remaining_eps: int,
    done_eps: int,
    done_requests: int,
    elapsed: float,
    long_wait_time: float,
    download_counter: int,
) -> float:
    """待ち時間の規則から本文取得の残り時間（秒）を見積もる

    N件ごとの長い待ちは発生回数が規則で決まるため、平均に混ぜず別に足す
    （tqdm標準の見積もりは長い待ちのたびに大きく跳ねる）

    remaining_eps: 残り話数
    done_eps / done_requests: 取得済みの話数と、その間のリクエスト数（挿絵を含む）
    elapsed / long_wait_time: 取得開始からの経過秒数と、そのうち長い待ちの秒数
    download_counter: 長い待ちの周期上の現在位置（NarouScraper.download_counter）
    """
    # 1話あたりのリクエスト数（本文 + 挿絵）。実績がなければ本文のみと仮定
    reqs_per_ep = done_requests / done_eps if done_requests else 1.0
    remaining_reqs = math.ceil(remaining_eps * reqs_per_ep)
    if remaining_reqs == 0:
        return 0.0

    # 長い待ちを除いた1リクエストあたりの実測時間（通信時間を含む）
    if done_requests:
        per_req = max((elapsed - long_wait_time) / done_requests, 0.0)
    else:
        per_req = DOWNLOAD_INTERVAL

    # 長い待ちは、カウンタが N の倍数（0を除く）のときのリクエスト直前に入る
    long_waits = 0
    if DOWNLOAD_WAIT_STEPS > 0:
        first = max(download_counter, 1)
        last = download_counter + remaining_reqs - 1
        long_waits = last // DOWNLOAD_WAIT_STEPS - (first - 1) // DOWNLOAD_WAIT_STEPS
    long_wait = max(STEPS_WAIT_TIME, DOWNLOAD_INTERVAL)

    return remaining_reqs * per_req + long_waits * long_wait


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
    # 残り時間はtqdm標準ではなく estimate_remaining の見積もりを表示する
    start_time = time.monotonic()
    start_requests = scraper.request_count
    start_long_wait = scraper.long_wait_total

    def eta_text(done_eps: int) -> str:
        eta = estimate_remaining(
            remaining_eps=len(episodes) - done_eps,
            done_eps=done_eps,
            done_requests=scraper.request_count - start_requests,
            elapsed=time.monotonic() - start_time,
            long_wait_time=scraper.long_wait_total - start_long_wait,
            download_counter=scraper.download_counter,
        )
        return f"残り約{tqdm.format_interval(eta)}"

    progress = tqdm(
        episodes,
        desc="本文取得中",
        unit="話",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}{postfix}]",
        postfix=eta_text(0),
    )
    for i, ep in enumerate(progress):
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
        progress.set_postfix_str(eta_text(i + 1), refresh=False)

    # 5. 章分割 + EPUB生成
    volumes = generator.split_into_volumes(toc["chapters"], episodes)
    for vol in tqdm(volumes, desc="EPUB生成中", unit="巻"):
        path = generator.generate(metadata, vol)
        tqdm.write(f"  生成: {path}")

    print("完了")


if __name__ == "__main__":
    main()
