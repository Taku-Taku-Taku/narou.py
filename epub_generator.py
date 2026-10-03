"""EPUB3生成"""

import io
import itertools
import os
import re

from ebooklib import epub
from PIL import Image

from parser import to_vertical_html

STYLESHEET = """\
@charset "UTF-8";
body {
  writing-mode: vertical-rl;
  -webkit-writing-mode: vertical-rl;
  -epub-writing-mode: vertical-rl;
  line-height: 1.8;
  margin: 0;
  padding: 0;
}
h1 {
  font-size: 1.5em;
  margin-bottom: 2em;
}
h2 {
  font-size: 1.2em;
  margin-bottom: 1em;
}
p {
  /* 字下げは本文の行頭全角スペースに任せる（CSSでも下げると二重になる） */
  text-indent: 0;
  margin: 0;
}
ruby {
  ruby-position: over;
}
rt {
  font-size: 0.5em;
}
em.sesame {
  font-style: normal;
  text-emphasis-style: filled sesame;
  -webkit-text-emphasis-style: filled sesame;
}
.illustration img {
  max-width: 100%;
  max-height: 90vh;
}
.titlepage {
  text-align: center;
  margin-top: 30%;
}
.titlepage h1 {
  font-size: 1.8em;
  margin-bottom: 1em;
}
.titlepage h2 {
  font-size: 1.3em;
  margin-bottom: 2em;
}
.titlepage .author {
  font-size: 1em;
}
nav.toc {
  margin-top: 2em;
}
nav.toc h2 {
  font-size: 1.2em;
  margin-bottom: 0.5em;
}
nav.toc ol {
  list-style: none;
  padding: 0;
}
nav.toc li {
  margin: 0.3em 0;
}
nav.toc a {
  text-decoration: none;
  color: inherit;
}
.ep-number {
  text-indent: 0;
  font-size: 0.85em;
  color: inherit;
  margin-bottom: 0.2em;
}
.tcy {
  text-combine-upright: all;
  -webkit-text-combine: horizontal;
  -epub-text-combine: horizontal;
}
.upright {
  text-orientation: upright;
  -webkit-text-orientation: upright;
  -epub-text-orientation: upright;
}
"""

# Send to Kindle上限200MBに対し余裕を持たせた分割閾値
# 本文(UTF-8)と挿絵(ダウンロード時点)の生サイズの合計で判定する
MAX_RAW_SIZE_BYTES = 180 * 1024 * 1024  # 180MB

IMAGE_QUALITY = 85

# 拡張子 → EPUBのコアメディアタイプ
MEDIA_TYPES = {"jpg": "image/jpeg"}


def _episode_size(ep: dict) -> int:
    """エピソードの本文と挿絵の合計バイト数"""
    body_size = len(ep.get("body", "").encode("utf-8"))
    image_size = sum(len(img["data"]) for img in ep.get("images", []))
    return body_size + image_size


class EpubGenerator:
    def __init__(
        self,
        output_dir: str = "output",
        image_max_width: int | None = None,
        image_max_height: int | None = None,
    ):
        self.output_dir = output_dir
        self.image_max_width = image_max_width
        self.image_max_height = image_max_height
        os.makedirs(output_dir, exist_ok=True)

    def optimize_image(self, data: bytes) -> tuple[bytes, str]:
        """画像を最適化し、(データ, 拡張子)を返す"""
        img = Image.open(io.BytesIO(data))
        if self.image_max_width and self.image_max_height:
            img.thumbnail(
                (self.image_max_width, self.image_max_height), Image.LANCZOS
            )
        # JPEGで保存できるのはRGB/Lのみ（RGBA, P, LA, CMYK, I;16 などはRGBに変換）
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=IMAGE_QUALITY)
        return buf.getvalue(), "jpg"

    def split_into_volumes(
        self, chapters: list[str], episodes: list[dict]
    ) -> list[dict]:
        """エピソードを巻に分割する

        デフォルト: 全話1ファイル
        サイズ超過時: 章の切れ目で分割（章なしの場合は均等分割）
        """
        total_size = sum(_episode_size(ep) for ep in episodes)

        if total_size <= MAX_RAW_SIZE_BYTES:
            # 1ファイルに収まる
            return [
                {
                    "number": 1,
                    "title": "",
                    "episodes": episodes,
                }
            ]

        # サイズ超過 → 章の切れ目で分割
        volumes = []
        if chapters:
            current_vol_eps = []
            current_size = 0

            # 掲載順に連続する同じ章のエピソードをまとめる
            # （章前のプロローグや同名の章があっても順序を保つ）
            for _, group in itertools.groupby(episodes, key=lambda e: e["chapter"]):
                chapter_eps = list(group)
                chapter_size = sum(_episode_size(e) for e in chapter_eps)

                # 現在の巻に追加するとサイズ超過、かつ既にエピソードがある場合は確定
                if current_vol_eps and current_size + chapter_size > MAX_RAW_SIZE_BYTES:
                    volumes.append(
                        {
                            "number": len(volumes) + 1,
                            "title": "",
                            "episodes": current_vol_eps,
                        }
                    )
                    current_vol_eps = []
                    current_size = 0

                current_vol_eps.extend(chapter_eps)
                current_size += chapter_size

            if current_vol_eps:
                volumes.append(
                    {
                        "number": len(volumes) + 1,
                        "title": "",
                        "episodes": current_vol_eps,
                    }
                )
        else:
            # 章なし → 均等分割
            num_vols = (total_size // MAX_RAW_SIZE_BYTES) + 1
            eps_per_vol = len(episodes) // num_vols + 1
            for i in range(0, len(episodes), eps_per_vol):
                chunk = episodes[i : i + eps_per_vol]
                volumes.append(
                    {
                        "number": len(volumes) + 1,
                        "title": "",
                        "episodes": chunk,
                    }
                )

        return volumes

    def generate(self, metadata: dict, volume: dict) -> str:
        """1巻分のEPUBを生成"""
        book = epub.EpubBook()

        # メタデータ設定
        ncode = metadata.get("ncode", "unknown").lower()
        title = metadata["title"]
        vol_subtitle = volume["title"]
        vol_title = f"{title} {vol_subtitle}" if vol_subtitle else title

        book.set_identifier(f"narou-{ncode}-vol{volume['number']}")
        book.set_title(vol_title)
        book.set_language("ja")
        book.add_author(metadata.get("writer", "不明"))

        # レイアウトメタデータ（縦書きはCSSのwriting-modeで制御）
        book.add_metadata(
            None,
            "meta",
            "reflowable",
            {"property": "rendition:layout"},
        )

        # 右綴じ（右→左ページ送り）
        book.set_direction("rtl")

        # CSS
        style = epub.EpubItem(
            uid="style",
            file_name="style/default.css",
            media_type="text/css",
            content=STYLESHEET.encode("utf-8"),
        )
        book.add_item(style)

        # 各エピソードをチャプターとして追加
        epub_chapters = []
        toc_items = []
        img_count = 0

        for ep in volume["episodes"]:
            chapter = epub.EpubHtml(
                title=ep["title"] or f"第{ep['number']}話",
                file_name=f"ep_{ep['number']:05d}.xhtml",
                lang="ja",
            )
            chapter.add_item(style)

            body = ep.get("body", "")

            # 画像をEPUBに埋め込み、srcを書き換え
            for img_data in ep.get("images", []):
                img_count += 1
                optimized, ext = self.optimize_image(img_data["data"])
                img_file = f"images/img_{img_count:04d}.{ext}"
                img_item = epub.EpubItem(
                    uid=f"img_{img_count}",
                    file_name=img_file,
                    media_type=MEDIA_TYPES[ext],
                    content=optimized,
                )
                book.add_item(img_item)
                body = body.replace(img_data["src"], img_file)

            heading = to_vertical_html(ep["title"] or f"第{ep['number']}話")
            total_ep = metadata.get("general_all_no", "")
            ep_info = f"#{ep['number']} / {total_ep}" if total_ep else f"#{ep['number']}"
            chapter.content = (
                f'<p class="ep-number">{to_vertical_html(ep_info)}</p>\n' f"<h2>{heading}</h2>\n{body}"
            )

            book.add_item(chapter)
            epub_chapters.append(chapter)
            toc_items.append(chapter)

        # 表紙ページ（タイトル + 章名 + 目次リンク）
        toc_link_items = []
        for ep in volume["episodes"]:
            num = ep["number"]
            ep_title = ep["title"] or f"第{num}話"
            toc_link_items.append(
                f'<li><a href="ep_{num:05d}.xhtml">'
                f"{to_vertical_html(f'#{num}　{ep_title}')}</a></li>"
            )
        toc_links = "\n".join(toc_link_items)
        title_page = epub.EpubHtml(
            title=vol_title,
            file_name="titlepage.xhtml",
            lang="ja",
        )
        title_page.add_item(style)
        subtitle_html = f"<h2>{to_vertical_html(vol_subtitle)}</h2>" if vol_subtitle else ""
        title_page.content = (
            f'<div class="titlepage">'
            f"<h1>{to_vertical_html(title)}</h1>"
            f"{subtitle_html}"
            f'<p class="author">{to_vertical_html(metadata.get("writer", "不明"))}</p>'
            f"</div>"
            f'<nav class="toc">'
            f"<h2>目次</h2>"
            f"<ol>{toc_links}</ol>"
            f"</nav>"
        )
        book.add_item(title_page)

        book.toc = toc_items
        book.spine = [title_page] + epub_chapters

        # ナビゲーション（EPUB仕様上必須だがspineには含めない）
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        # 書き出し
        eps = volume["episodes"]
        first_ep = eps[0]["number"]
        last_ep = eps[-1]["number"]
        # ファイル名に使えない文字を除去
        safe_title = re.sub(r'[\\/:*?"<>|]', "", title)
        filename = f"{safe_title}({ncode})_{first_ep}-{last_ep}.epub"
        filepath = os.path.join(self.output_dir, filename)
        epub.write_epub(filepath, book)
        return filepath
