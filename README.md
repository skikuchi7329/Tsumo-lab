# Tsumo-Lab

パチスロホールの出玉データを自動収集・分析し、**狙い目の機種を数値で可視化**する傾向分析ツール。

みんレポ (min-repo.com) のレポートデータを元に、特定日・ゾロ目日・曜日・祝日ごとの機種別傾向を解析し、
独自スコアリング「**Tsumo-Rank**」でおすすめ機種をランキング化する。

---

## 主な機能

| 機能 | 説明 |
|:---|:---|
| 自動スクレイピング | みんレポのタグページから最新レポートを取得し SQLite に蓄積 |
| 特定日分析 | 日付の1の位 (0〜9) ごとに強い機種を分析 |
| ゾロ目日分析 | 11日・22日・月=日 (7/7 等) の傾向を抽出 |
| 新装開店分析 | 前日データがない日 (休業明け) の機種傾向 |
| 曜日・祝日分析 | 曜日別・祝日の傾向を集計 |
| Tsumo-Rank | 独自スコアで機種をランキング |
| 全台系検出 | 勝率 75%以上 + 平均差枚 +1,000 以上の日を自動判定 |
| 機種名名寄せ | 表記揺れ (例: 「L北斗の拳」↔「スマスロ北斗」) を統一集計 |
| Markdown レポート | 分析結果を見やすいレポートとしてファイル出力 |
| 日次バッチ | cron 対応のバッチスクリプトで完全自動運用 |

---

## クイックスタート

### 必要環境

- Python 3.10+
- pip

### インストール

```bash
git clone https://github.com/your-org/Tsumo-lab.git
cd Tsumo-lab
pip install -r requirements.txt
```

### 基本的な使い方

```bash
# 1. スクレイピング (データ収集 → DB 保存)
python main.py scrape

# 2. 傾向分析 (DB のデータ → Markdown レポート出力)
python main.py analyze

# 3. 特定店舗のみスクレイピング (店舗名で指定)
python main.py scrape --shop-name 麗都荒川沖

# 4. 特定店舗のみ分析 + コンソール表示
python main.py analyze --shop-name 麗都荒川沖 --console

# 5. 日次バッチ (スクレイピング + 分析を一括実行)
python scripts/daily_update.py

# 6. 分析のみバッチ実行
python scripts/daily_update.py --analyze-only
```

レポートは `output/report_{shop_id}_{date}.md` に出力される。

---

## Tsumo-Rank スコアリング

Tsumo-Rank は、各機種の「狙い目度」を定量化する独自スコア。

```
Tsumo-Rank = (平均差枚 × 0.4) + (勝率 × 10) + (全台系回数 × 100)
```

| 要素 | 重み | 説明 |
|:---|:---|:---|
| 平均差枚 | ×0.4 | 出玉の絶対量を評価 |
| 勝率 (%) | ×10 | 勝ちやすさを評価 (安定性) |
| 全台系回数 | ×100 | ホールが力を入れた回数をボーナス評価 |

### 全台系の判定基準

以下の **両方** を満たす日を「全台系」としてカウント:

- 勝率 **75%** 以上
- 平均差枚 **+1,000** 以上

### スコア計算例

| 機種 | 平均差枚 | 勝率 | 全台系 | スコア |
|:---|---:|---:|---:|---:|
| マイジャグラーV | +1,050 | 73.8% | 3回 | 420 + 738 + 300 = **1,458** |
| アイムジャグラーEX | +500 | 60.0% | 1回 | 200 + 600 + 100 = **900** |

---

## ディレクトリ構成

```
Tsumo-lab/
├── main.py                    # CLI エントリポイント (scrape / analyze)
├── requirements.txt           # Python 依存パッケージ
├── README.md
│
├── config/
│   ├── config.yaml            # 店舗設定 (店舗ID, タグ名, 特定日)
│   └── machine_alias.yaml     # 機種名エイリアス (名寄せ定義)
│
├── scrapers/
│   └── min_repo_scraper.py    # みんレポ 2段階スクレイパー
│
├── database/
│   └── db_handler.py          # SQLite / JSON 永続化
│
├── analysis/
│   └── trend_analyzer.py      # 傾向分析エンジン + Tsumo-Rank
│
├── models/
│   └── schema.py              # データモデル (SlotData, MachineStats)
│
├── utils/
│   ├── date_helper.py         # 日付属性分析 (特定日, ゾロ目, 祝日)
│   ├── parser_helper.py       # 数値変換 (全角, マイナス記号, カンマ)
│   ├── machine_alias.py       # 機種名名寄せリゾルバ
│   └── logger.py              # ログ設定 (ファイルローテーション)
│
├── scripts/
│   └── daily_update.py        # 日次バッチスクリプト
│
├── tests/
│   ├── test_scraper.py        # スクレイパー + DB テスト (53件)
│   └── test_analyzer.py       # 分析エンジン テスト (25件)
│
├── data/                      # DB / CSV (gitignore 対象)
├── output/                    # 生成レポート
└── logs/                      # ログファイル (自動ローテーション)
```

---

## サポート店舗の追加方法

### 1. config/config.yaml に店舗を追加

```yaml
shops:
  - name: "新規店舗名"
    tag_name: "%E6%96%B0%E8%A6%8F"   # URL エンコード済みタグ名
    shop_id: "999"
    area: "東京都"
    day_suffix_targets: [3, 7]         # 強い日の1の位
    zoro_target: true
    notes: ""
```

**tag_name の取得方法:**

1. [min-repo.com](https://min-repo.com) で対象店舗のタグページを開く
2. URL の `/tag/` 以降の部分をコピー
   - 例: `https://min-repo.com/tag/%E9%BA%97%E9%83%BD%E8%8D%92%E5%B7%9D%E6%B2%96/`
   - → `%E9%BA%97%E9%83%BD%E8%8D%92%E5%B7%9D%E6%B2%96`

### 2. 機種名の表記揺れがある場合

`config/machine_alias.yaml` にエイリアスを追加:

```yaml
aliases:
  "正規名称":
    - "別名1"
    - "別名2"
```

### 3. 実行

```bash
python main.py scrape     # 新店舗のデータを収集
python main.py analyze    # 全店舗を分析
```

---

## 日次バッチの設定 (cron)

```bash
# crontab -e で以下を追加 (毎日 3:00 に実行)
0 3 * * * cd /path/to/Tsumo-lab && /path/to/python scripts/daily_update.py
```

ログは `logs/tsumo_lab.log` に自動出力される (5MB × 3世代でローテーション)。

エラー発生時もプロセスは停止せず、ログにスタックトレースが記録される。

---

## 技術仕様

| 項目 | 内容 |
|:---|:---|
| データソース | min-repo.com (みんレポ) |
| パーサー | BeautifulSoup4 + lxml |
| DB | SQLite (WAL モード, UNIQUE 制約で重複防止) |
| 祝日判定 | `holidays` ライブラリ (日本の祝日) |
| テスト | pytest (78+ テスト) |
| ログ | RotatingFileHandler (5MB × 3世代) |

---

## ライセンス

Private — All rights reserved.
