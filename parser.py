"""ルビ記法パーサー・テキスト変換

なろう記法:
  ｜親文字《ルビ》  → <ruby>親文字<rp>（</rp><rt>ルビ</rt><rp>）</rp></ruby>
  漢字《ルビ》      → <ruby>漢字<rp>（</rp><rt>ルビ</rt><rp>）</rp></ruby>
  《《傍点対象》》  → <em class="sesame">傍点対象</em>

数字変換（縦書き対応）:
  1桁・3桁以上 → 全角数字 (0→０)
  2桁         → 縦中横 <span class="tcy">
"""

import re

# 漢字の範囲（CJK統合漢字 + 拡張A）
_KANJI = r"\u3400-\u9FFF\uF900-\uFAFF"
# ルビ対象になる文字（漢字 + 一部の記号）
_RUBY_TARGET = rf"[{_KANJI}々〇〻]"

# ｜親文字《ルビ》 パターン（明示的指定）
_EXPLICIT_RUBY = re.compile(
    r"[｜|](.+?)《(.+?)》"
)

# 漢字《ルビ》 パターン（自動検出）
_AUTO_RUBY = re.compile(
    rf"({_RUBY_TARGET}+)《(.+?)》"
)

# 《《傍点》》 パターン
_SESAME = re.compile(
    r"《《(.+?)》》"
)


def _ruby_tag(base: str, ruby: str) -> str:
    return f"<ruby>{base}<rp>（</rp><rt>{ruby}</rt><rp>）</rp></ruby>"


# 半角→全角変換テーブル
_NUM_TO_ZENKAKU = str.maketrans("0123456789", "０１２３４５６７８９")
_ALPHA_TO_ZENKAKU = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ",
)

# HTMLタグを避けてテキスト部分だけを処理するためのパターン
_TEXT_OUTSIDE_TAGS = re.compile(r"([^<>]+)(?=<|$)")

# HTMLエンティティ（&amp; &#12345; &#x3042; など）。変換対象から除外する
_ENTITY = re.compile(r"(&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);)")

# テキスト中の半角数字の連続
_HANKAKU_NUM = re.compile(r"\d+")

# 半角英字・数字・記号が連続する部分（英文検出用）
# ※Pythonの\wはUnicode(日本語含む)にマッチするため、ASCII明示指定
_ENGLISH_CHARS = re.compile(r"[a-zA-Z0-9_.,!?'\" &:;-]+")

# 英文とみなす最小文字数（これ以上でアルファベットを含めば半角維持）
_ENGLISH_MIN_LENGTH = 8


def _convert_num(match: re.Match) -> str:
    """半角数字を縦書き向けに変換

    1桁・3桁以上: 全角数字に変換
    2桁: 縦中横（text-combine-upright）で半角のまま表示
    """
    num = match.group(0)
    if len(num) == 2:
        return f'<span class="tcy">{num}</span>'
    return num.translate(_NUM_TO_ZENKAKU)


def _is_english_sentence(text: str) -> bool:
    """2単語以上のスペース区切り、または一定長以上でアルファベットを含む"""
    if len(text.split()) >= 2:
        return True
    return len(text) >= _ENGLISH_MIN_LENGTH and re.search(r"[a-zA-Z]", text)


def _convert_alpha(match: re.Match) -> str:
    """半角英字を縦書き向けに変換（Rubyプロダクトと同等のロジック）

    英文（2単語以上 or 8文字以上）: 半角のまま維持
    短い英字: 全角化
    アルファベットを含まない場合はスキップ（数字変換に任せる）
    """
    text = match.group(0)
    if not re.search(r"[a-zA-Z]", text):
        return text
    if _is_english_sentence(text):
        return text
    return text.translate(_ALPHA_TO_ZENKAKU)


def _convert_plain_text(text: str) -> str:
    """エンティティを含まないテキストの英字・数字を変換"""
    # 英字を先に変換（全角化済みの文字は数字パターンに干渉しない）
    text = _ENGLISH_CHARS.sub(_convert_alpha, text)
    # 残った半角数字を変換（英文中の数字は英字変換でスキップ済み）
    text = _HANKAKU_NUM.sub(_convert_num, text)
    return text


def _convert_text_segment(match: re.Match) -> str:
    """HTMLタグの外側のテキスト部分のみ英字・数字を変換

    HTMLエンティティは壊さないようにそのまま残す
    """
    # splitの結果は奇数番目がエンティティ
    parts = _ENTITY.split(match.group(0))
    return "".join(
        part if i % 2 else _convert_plain_text(part) for i, part in enumerate(parts)
    )


class RubyParser:
    def convert(self, html: str) -> str:
        """本文HTML中のなろうルビ記法をHTMLルビタグに変換"""
        # 傍点を先に処理（《《》》が《》と誤マッチしないように）
        text = _SESAME.sub(
            r'<em class="sesame">\1</em>',
            html,
        )
        # 明示的ルビ（｜指定）
        text = _EXPLICIT_RUBY.sub(
            lambda m: _ruby_tag(m.group(1), m.group(2)),
            text,
        )
        # 自動ルビ（漢字のみ）
        text = _AUTO_RUBY.sub(
            lambda m: _ruby_tag(m.group(1), m.group(2)),
            text,
        )
        # 数字・英字の縦書き変換（タグ外のテキスト部分のみ）
        text = _TEXT_OUTSIDE_TAGS.sub(_convert_text_segment, text)
        return text
