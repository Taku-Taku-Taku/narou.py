"""なろうスクレイピング処理"""

import hashlib
import time

import requests
from bs4 import BeautifulSoup

API_URL = "https://api.syosetu.com/novelapi/api/"
BASE_URL = "https://ncode.syosetu.com"

# レート制限設定（robots.txt の Crawl-delay: 1 を遵守）
DOWNLOAD_INTERVAL = 1.1  # 1話ごとのウェイト（秒）※robots.txt Crawl-delay準拠
DOWNLOAD_WAIT_STEPS = 10  # N話ごとに長めのウェイトを入れる
STEPS_WAIT_TIME = 5.0  # N話ごとの長いウェイト時間（秒）
API_REQUEST_INTERVAL = 3.0  # なろうAPIリクエスト間のウェイト（秒）


class NarouScraper:
    def __init__(self, cache=None):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "narou.py/1.1.0"})
        self.cache = cache
        self._last_download_time = 0.0
        self._download_counter = 0
        self._last_api_time = 0.0
        self._is_first_api_request = True

    @staticmethod
    def _strip_web_attrs(element):
        """EPUB不要なWeb属性を除去（Kindleレンダリング負荷軽減）

        - 全要素: style属性、Web用class属性を除去
        - p要素: id属性を除去（id="L1"等のなろう内部用）
        """
        for tag in element.find_all(True):
            tag.attrs.pop("style", None)
            tag.attrs.pop("class", None)
            if tag.name == "p":
                tag.attrs.pop("id", None)
        # element自身も処理
        element.attrs.pop("style", None)
        element.attrs.pop("class", None)

    def _wait_for_download(self):
        """各話ダウンロード用のレート制限（Rubyプロダクトと同等のロジック）

        - 毎話: DOWNLOAD_INTERVAL 秒待機
        - DOWNLOAD_WAIT_STEPS 話ごと: STEPS_WAIT_TIME 秒の長めの待機
        - 小説家になろうは連続DL規制があるため、10話ごとにウェイトを挟む
        """
        now = time.monotonic()
        max_wait = max(STEPS_WAIT_TIME, DOWNLOAD_INTERVAL)

        # 前回DLから十分時間が経っていればカウンタをリセット
        if now - self._last_download_time > max_wait:
            self._download_counter = 0

        if (
            self._download_counter > 0
            and DOWNLOAD_WAIT_STEPS > 0
            and self._download_counter % DOWNLOAD_WAIT_STEPS == 0
        ):
            # N話ごとの長めのウェイト
            time.sleep(max_wait)
        elif self._download_counter > 0:
            # 通常の1話ごとのウェイト
            elapsed = now - self._last_download_time
            if elapsed < DOWNLOAD_INTERVAL:
                time.sleep(DOWNLOAD_INTERVAL - elapsed)

        self._download_counter += 1
        self._last_download_time = time.monotonic()

    def _wait_for_api(self):
        """なろうAPIリクエスト用のレート制限（初回は除く）"""
        if self._is_first_api_request:
            self._is_first_api_request = False
            return
        elapsed = time.monotonic() - self._last_api_time
        if elapsed < API_REQUEST_INTERVAL:
            time.sleep(API_REQUEST_INTERVAL - elapsed)
        self._last_api_time = time.monotonic()

    def fetch_metadata(self, ncode: str) -> dict | None:
        """なろうAPIでメタデータを取得

        総話数などの更新を検知するため、キャッシュは使わず毎回APIに問い合わせる
        """
        params = {
            "out": "json",
            "ncode": ncode,
            "lim": 1,
        }
        self._wait_for_api()
        resp = self.session.get(API_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        # APIは先頭に件数情報が入る
        if len(data) < 2:
            return None

        # 存在しないncodeだとAPIは条件を無視して無関係な作品を返すため照合する
        metadata = data[1]
        if metadata.get("ncode", "").lower() != ncode.lower():
            return None
        return metadata

    def fetch_toc(self, ncode: str, total_episodes: int | None = None) -> dict:
        """目次ページから章構造とエピソード一覧を取得（複数ページ対応）

        total_episodes を指定すると、キャッシュの話数と一致する場合のみキャッシュを使う
        （新話の追加・削除があれば目次を取り直す）
        """
        cached = self.cache.get("toc", ncode) if self.cache else None
        if cached and (
            total_episodes is None or len(cached["episodes"]) == total_episodes
        ):
            return cached

        chapters = []
        episodes = []
        current_chapter = None
        episode_number = 0
        page = 1

        while True:
            self._wait_for_download()
            url = f"{BASE_URL}/{ncode}/"
            if page > 1:
                url += f"?p={page}"
            resp = self.session.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # 新レイアウト (p-eplist) または旧レイアウト (index_box) を検出
            eplist = soup.select_one(".p-eplist")
            index_box = soup.select_one(".index_box")

            if eplist:
                for child in eplist.children:
                    if not hasattr(child, "get"):
                        continue
                    cls = child.get("class", [])

                    if "p-eplist__chapter-title" in cls:
                        current_chapter = child.get_text(strip=True)
                        if current_chapter not in chapters:
                            chapters.append(current_chapter)

                    elif "p-eplist__sublist" in cls:
                        episode_number += 1
                        a_tag = child.select_one("a.p-eplist__subtitle")
                        title = a_tag.get_text(strip=True) if a_tag else ""
                        episodes.append(
                            {
                                "number": episode_number,
                                "title": title,
                                "chapter": current_chapter,
                            }
                        )

            elif index_box:
                for child in index_box.children:
                    if not hasattr(child, "get"):
                        continue
                    cls = child.get("class", [])

                    if "chapter_title" in cls:
                        current_chapter = child.get_text(strip=True)
                        if current_chapter not in chapters:
                            chapters.append(current_chapter)

                    elif "novel_sublist2" in cls:
                        episode_number += 1
                        a_tag = child.select_one("a")
                        title = a_tag.get_text(strip=True) if a_tag else ""
                        episodes.append(
                            {
                                "number": episode_number,
                                "title": title,
                                "chapter": current_chapter,
                            }
                        )

            else:
                if page == 1:
                    # 短編（目次なし）
                    episodes.append(
                        {
                            "number": 1,
                            "title": "",
                            "chapter": None,
                        }
                    )
                break

            # 次ページがあるか確認
            next_link = soup.select_one("a.c-pager__item--next")
            if next_link:
                page += 1
            else:
                break

        result = {"chapters": chapters, "episodes": episodes}
        if self.cache:
            self.cache.set("toc", ncode, result)
        return result

    def fetch_episode(self, ncode: str, number: int) -> str:
        """エピソード本文HTMLを取得"""
        cached = self.cache.get("episode", f"{ncode}_{number}") if self.cache else None
        if cached:
            return cached

        self._wait_for_download()
        resp = self.session.get(f"{BASE_URL}/{ncode}/{number}/")
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # 新レイアウト: .p-novel__body 内の .p-novel__text
        # 旧レイアウト: #novel_honbun
        body = soup.select_one(".p-novel__body")
        if body:
            # 前書き・本文・あとがきをすべて含む
            # 前書き・後書きが存在する場合は区切り線を挿入
            sections = body.select(".p-novel__text")
            if not sections:
                return ""
            parts = []
            prev_type = None
            for section in sections:
                cls = section.get("class", [])
                if "p-novel__text--preface" in cls:
                    cur_type = "preface"
                elif "p-novel__text--afterword" in cls:
                    cur_type = "afterword"
                else:
                    cur_type = "body"
                # セクション種別が変わる境界に区切り線を挿入
                if prev_type is not None and prev_type != cur_type:
                    parts.append("<hr />")
                self._strip_web_attrs(section)
                # divラッパーを除去し中身だけを取得（DOM階層を浅くする）
                parts.append(section.decode_contents())
                prev_type = cur_type
            html = "\n".join(parts)
        else:
            honbun = soup.select_one("#novel_honbun")
            if honbun is None:
                return ""
            self._strip_web_attrs(honbun)
            html = honbun.decode_contents()
        if self.cache:
            self.cache.set("episode", f"{ncode}_{number}", html)
        return html

    def fetch_image(self, ncode: str, url: str) -> bytes:
        """画像をダウンロード（キャッシュはncode単位で削除できるようncodeを接頭辞にする）"""
        key = f"{ncode}_{hashlib.sha1(url.encode('utf-8')).hexdigest()}"
        cached = self.cache.get_bytes("image", key) if self.cache else None
        if cached:
            return cached

        self._wait_for_download()
        resp = self.session.get(url)
        resp.raise_for_status()
        if self.cache:
            self.cache.set_bytes("image", key, resp.content)
        return resp.content
