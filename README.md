# Daily Stock Advisor

日米株式市場をテクニカル分析でスクリーニングし、毎営業日の推奨銘柄TOP10を表示するツール。

## アーキテクチャ

```
GitHub Actions (毎日 8:00 JST)
   ↓ 実行
scripts/analyze.py  ──→  yfinance API
   ↓ 出力
data/recommendations.json
   ↓ 自動 commit & push
   ↓ 読み込み
index.html (GitHub Pages or ローカル)
```

## ディレクトリ構成

```
stock-advisor/
├── .github/workflows/daily-analysis.yml   # 自動実行ワークフロー
├── scripts/
│   ├── analyze.py                         # メイン分析スクリプト
│   ├── requirements.txt
│   ├── dry_run.py                         # 合成データでロジック検証
│   └── gen_sample_data.py                 # UI確認用ダミーJSON生成
├── data/
│   └── recommendations.json               # 分析結果(自動更新)
└── index.html                             # ダッシュボード
```

## セットアップ

### 1. GitHubリポジトリ作成

```bash
cd stock-advisor
git init
git add .
git commit -m "Initial commit"
gh repo create stock-advisor --public --source=. --push
```

### 2. GitHub Pages有効化

Settings → Pages → Source: `main` branch, `/` (root) → Save

数分後、`https://<username>.github.io/stock-advisor/` でアクセス可能に。

### 3. 初回手動実行

Actions タブ → "Daily Stock Analysis" → "Run workflow" → 実行

数分でcommitが追加され、`data/recommendations.json` が更新される。

## 動作確認(ローカル)

```bash
# 依存をインストール
pip install -r scripts/requirements.txt

# 実データで実行
python scripts/analyze.py

# ロジックを合成データで検証
python scripts/dry_run.py

# UI用のダミーデータを生成
python scripts/gen_sample_data.py

# HTMLをブラウザで確認(file://でも動作するが、CORSのためローカルサーバー推奨)
python -m http.server 8000
# http://localhost:8000 でアクセス
```

## スコアリング仕様

総合スコア(0-100)は以下の重み付き平均:

| 指標 | 重み | ロジック |
|------|------|---------|
| トレンド | 25% | SMA25/75/200のパーフェクトオーダー判定 |
| RSI | 20% | 30近辺で高得点、70超で低得点 |
| MACD | 20% | ゴールデンクロス直後で高得点 |
| ボリンジャー | 15% | 下限タッチで高得点 |
| 出来高 | 10% | 直近5日平均/20日平均 |
| モメンタム | 10% | 直近5日リターン |

## カスタマイズポイント

- **対象銘柄**: `scripts/analyze.py` の `JP_UNIVERSE`, `US_UNIVERSE`
- **スコア重み**: `SCORE_WEIGHTS`
- **TOP N**: `TOP_N` (デフォルト10)
- **実行時刻**: `.github/workflows/daily-analysis.yml` の cron 式

## データソースについて

無料の yfinance を利用。短期トレード向けには日次データで十分だが、**個人利用の範囲**にとどめること。本格的・商用利用には [J-Quants API Light](https://jpx-jquants.com/) (1,650円/月) への移行を検討。

## 免責

本ツールはテクニカル指標のみに基づく機械的スコアリングであり、投資推奨ではない。投資判断は自己責任で。
