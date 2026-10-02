# narou.py

## 概要
小説家になろうの作品を Kindle 向け縦書き EPUB に変換する Python CLI ツールです。
ある程度の校正機能もついています。（例：一桁の数字は縦書きに）

**[小説家になろう](http://syosetu.com/) のみ**に対応しています。


## 必要環境

- Python 3.12+
- uv
  - pythonであればどれでも可能ですが、依存関係が楽なのでuvをお勧めします
  - インストール方法は後述

## インストール&セットアップ

[Releaseページ](https://github.com/Taku-Taku-Taku/narou.py/releases/)から最新版をダウンロード＆展開
```bash
uv sync
```
- [uvのinstall方法はこちら](https://docs.astral.sh/uv/getting-started/installation/) 

## 使い方

コマンドはすべて、展開したフォルダの中で実行してください。

```bash
# 作品全話を変換
uv run main.py <ncode>

# 話数を指定して変換 (例：1〜10話)
uv run main.py <ncode> --start 1 --end 10

# 画像サイズを指定 (指定しなければ元の解像度のまま)
uv run main.py <ncode> --image-size medium

# 出力先を指定 (デフォルト: 実行したフォルダの output/)
uv run main.py <ncode> -o ./my_output

# キャッシュを使わずに取得 (改稿された話を取り直したいとき)
uv run main.py <ncode> --no-cache

# 特定作品のキャッシュを削除してから、取り直して変換
uv run main.py <ncode> --clear-cache

# 全キャッシュを削除 (変換はしない)
uv run main.py --clear-cache
```

<details>
<summary>ncodeとは？</summary>

各小説のURL https://ncode.syosetu.com/n0498fr/ （例：病毒の王 水木あおい）の **n0498fr** の部分です。
大文字・小文字はどちらでも構いません。作品ページのURL（例：`https://ncode.syosetu.com/n0498fr/`）をそのまま指定することもできます。

</details>

### 出力されるファイル

- `output/作品タイトル(ncode)_開始話-終了話.epub` という名前で保存されます。
- 挿絵を含めて180MBを超える場合は、章の区切りで複数のファイルに分割されます。

### Kindle への転送

> [!IMPORTANT]
> Kindle 端末は EPUB を直接読めません。EPUB を USB でそのままコピーしても、ライブラリに表示されません。

**Send to Kindle（おすすめ）**

[Send to Kindle](https://www.amazon.co.jp/sendtokindle/) で送ると、Amazon 側で Kindle 用の形式に変換されて端末に届きます。
送信できる容量が大きい（200MB）ので Web 版がおすすめです。

**USB 接続で転送する場合**

1. [Calibre](https://calibre-ebook.com/) で EPUB を **AZW3** 形式に変換する
2. Kindle をパソコンに接続し、`documents` フォルダにコピーする

| | Send to Kindle | USB（AZW3 に変換） |
|---|---|---|
| 変換の手間 | 不要 | Calibre での変換が必要 |
| 容量の上限 | 200MB（Web 版） | なし |
| ネット接続 | 必要 | 不要 |
| 読書位置の同期・他端末での閲覧 | できる | できない（その端末のみ） |

### オプション一覧

| オプション | 説明 |
|---|---|
| `--start N` | 開始話数 |
| `--end N` | 終了話数 |
| `--image-size` | 挿絵の最大解像度。`small` (6型: 1072×1448) / `medium` (7型: 1236×1648) / `large` (10型: 1860×2480)。未指定時はリサイズなし |
| `-o`, `--output` | 出力フォルダ (デフォルト: `output`。無ければ自動で作成) |
| `--no-cache` | キャッシュを読み書きせず、すべてサイトから取得する |
| `--clear-cache` | キャッシュを削除する。ncode を指定するとその作品のキャッシュだけを削除し、続けて変換も行う |

### キャッシュについて

- 一度取得した本文・目次・挿絵は、ツールのフォルダ内の `cache/` に保存され、次回からはサイトにアクセスせずに使われます。
- 連載中の作品で新しい話が追加された場合は、自動で目次を取り直します。
- すでに取得済みの話が**改稿された場合は自動では反映されません**。`--no-cache` か `--clear-cache` を使ってください。
- サイトへの負荷を抑えるため、1話ごとに約1秒、10話ごとに5秒の待ち時間を入れています。話数の多い作品は時間がかかります。


## 更新履歴
- 2026/2/15　リリース
- 2026/10/3　v1.1.0：変換時の文字化け・画像まわりの不具合を修正、連載中作品の新話を自動取得

もし、不具合・改善点等ありましたら、issueやpull requestなどを送っていただければ幸いです。

----

## 謝辞

本ツールは [whiteleaf](https://github.com/whiteleaf7) 氏の [Narou.rb](https://github.com/whiteleaf7/narou) を参考に開発されました。


## 免責事項

本ソフトウェアの使用または使用不能により生じた損害について、作者は一切の責任を負いません。
利用者は、対象サイトの利用規約・関連法令・著作権等を自己責任で遵守してください。作者は利用者の行為について責任を負いません。

----
「小説家になろう」は株式会社ヒナプロジェクトの登録商標です
