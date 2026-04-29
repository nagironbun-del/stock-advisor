"""
Daily Stock Advisor - Technical Analysis Engine
================================================
出来高上位銘柄をyfinanceから取得し、テクニカル指標でスコアリング。
TOP10銘柄をJSONとして出力する。

実行: python scripts/analyze.py
出力: data/recommendations.json
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# =============================================================================
# 設定
# =============================================================================

# スキャン対象の母集団 (流動性・知名度の高い銘柄を中心に)
# 出来高上位を「動的抽出」する母集団。ここから出来高フィルタで絞り込む。
JP_UNIVERSE = [
    # 自動車
    "7203.T", "7267.T", "7201.T", "7269.T", "7270.T",
    # 電機・精密
    "6758.T", "6501.T", "6503.T", "6594.T", "6981.T", "6861.T", "7751.T", "7741.T",
    # 半導体・装置
    "8035.T", "6920.T", "6857.T", "6146.T",
    # IT・通信
    "9984.T", "9433.T", "9434.T", "9432.T", "4689.T", "4324.T", "4755.T",
    # 金融
    "8306.T", "8316.T", "8411.T", "8604.T", "8766.T", "8725.T",
    # 商社
    "8001.T", "8002.T", "8031.T", "8053.T", "8058.T",
    # 小売・消費
    "9983.T", "3382.T", "8267.T", "7974.T",
    # 製薬・ヘルスケア
    "4502.T", "4503.T", "4519.T", "4523.T", "4568.T",
    # 素材・化学
    "4063.T", "4452.T", "3407.T", "5401.T", "5713.T",
    # その他大型
    "6098.T", "9020.T", "9101.T", "9201.T", "6367.T", "6273.T",
]

US_UNIVERSE = [
    # メガキャップ・テック
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    # 半導体
    "AMD", "INTC", "AVGO", "QCOM", "MU", "TSM", "ASML",
    # ソフトウェア・クラウド
    "ORCL", "CRM", "ADBE", "NOW", "SNOW", "PLTR",
    # 金融
    "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA",
    # ヘルスケア
    "JNJ", "UNH", "LLY", "PFE", "MRK", "ABBV",
    # 消費財
    "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "DIS",
    # エネルギー
    "XOM", "CVX",
    # その他大型
    "BRK-B", "BA", "CAT", "GE", "F", "GM",
    # 高ボラ・人気銘柄
    "COIN", "MARA", "RIOT", "SOFI", "RBLX", "U", "NET", "DDOG",
]

# テクニカル指標のスコア重み
SCORE_WEIGHTS = {
    "trend": 25,        # 移動平均トレンド
    "rsi": 20,          # RSI (買われすぎ/売られすぎ)
    "macd": 20,         # MACD ゴールデン/デッドクロス
    "bollinger": 15,    # ボリンジャーバンド
    "volume": 10,       # 出来高
    "momentum": 10,     # 直近モメンタム
}

TOP_N = 10           # 最終出力する銘柄数
LOOKBACK_DAYS = 200  # 取得する過去日数 (200日線計算のため)


# =============================================================================
# テクニカル指標計算
# =============================================================================

def calc_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_bollinger(series: pd.Series, period: int = 20, num_std: float = 2.0):
    sma = calc_sma(series, period)
    std = series.rolling(window=period, min_periods=period).std()
    upper = sma + num_std * std
    lower = sma - num_std * std
    return upper, sma, lower


# =============================================================================
# スコアリング
# =============================================================================

def score_trend(close: pd.Series, sma25: pd.Series, sma75: pd.Series, sma200: pd.Series) -> tuple[float, str]:
    """移動平均トレンドスコア (0-100)"""
    c = close.iloc[-1]
    s25 = sma25.iloc[-1]
    s75 = sma75.iloc[-1]
    s200 = sma200.iloc[-1] if not pd.isna(sma200.iloc[-1]) else s75

    score = 50
    note = ""
    # パーフェクトオーダー (上昇)
    if c > s25 > s75 > s200:
        score = 95
        note = "強い上昇トレンド (パーフェクトオーダー)"
    elif c > s25 > s75:
        score = 80
        note = "上昇トレンド"
    elif c > s25 and s25 < s75:
        score = 60
        note = "短期反発・押し目"
    elif c < s25 < s75 < s200:
        score = 10
        note = "強い下降トレンド"
    elif c < s25 < s75:
        score = 25
        note = "下降トレンド"
    else:
        score = 50
        note = "もみ合い"
    return score, note


def score_rsi(rsi: pd.Series) -> tuple[float, str]:
    """RSIスコア (0-100): 30近辺で高得点 (反発期待)"""
    r = rsi.iloc[-1]
    if pd.isna(r):
        return 50, "RSI算出不能"
    if r < 30:
        return 90, f"売られすぎ (RSI={r:.1f})"
    if r < 40:
        return 75, f"やや売られすぎ (RSI={r:.1f})"
    if 40 <= r <= 60:
        return 55, f"中立 (RSI={r:.1f})"
    if r < 70:
        return 45, f"やや買われすぎ (RSI={r:.1f})"
    return 15, f"買われすぎ (RSI={r:.1f})"


def score_macd(macd: pd.Series, signal: pd.Series, hist: pd.Series) -> tuple[float, str]:
    """MACDスコア: ゴールデンクロス直後に高得点"""
    if len(hist) < 3 or pd.isna(hist.iloc[-1]):
        return 50, "MACD算出不能"

    h_now = hist.iloc[-1]
    h_prev = hist.iloc[-2]

    # ゴールデンクロス (直前まで負、今が正)
    if h_prev <= 0 and h_now > 0:
        return 95, "MACDゴールデンクロス発生"
    # デッドクロス
    if h_prev >= 0 and h_now < 0:
        return 10, "MACDデッドクロス発生"
    # ヒストグラム拡大中(プラス圏)
    if h_now > 0 and h_now > h_prev:
        return 75, "MACD強気拡大中"
    if h_now > 0:
        return 60, "MACD強気だが鈍化"
    if h_now < 0 and h_now > h_prev:
        return 45, "MACD弱気だが収束中"
    return 25, "MACD弱気拡大中"


def score_bollinger(close: pd.Series, upper: pd.Series, mid: pd.Series, lower: pd.Series) -> tuple[float, str]:
    """ボリンジャーバンドスコア: 下限タッチで高得点 (反発狙い)"""
    c = close.iloc[-1]
    u = upper.iloc[-1]
    m = mid.iloc[-1]
    l = lower.iloc[-1]

    if pd.isna(u) or pd.isna(l):
        return 50, "BB算出不能"

    band_width = u - l
    if band_width == 0:
        return 50, "BB幅0"
    pos = (c - l) / band_width  # 0=下限, 1=上限

    if pos < 0.1:
        return 90, "BB下限タッチ (反発期待)"
    if pos < 0.3:
        return 70, "BB下半分 (買い候補)"
    if pos > 0.9:
        return 15, "BB上限タッチ (過熱)"
    if pos > 0.7:
        return 35, "BB上半分 (やや過熱)"
    return 55, "BB中央付近"


def score_volume(volume: pd.Series) -> tuple[float, str]:
    """出来高スコア: 直近5日平均が20日平均を上回ると高得点"""
    if len(volume) < 20:
        return 50, "出来高算出不能"
    v_recent = volume.iloc[-5:].mean()
    v_avg = volume.iloc[-20:].mean()
    if v_avg == 0 or pd.isna(v_avg):
        return 50, "出来高0"
    ratio = v_recent / v_avg
    if ratio > 2.0:
        return 90, f"出来高急増 ({ratio:.1f}倍)"
    if ratio > 1.5:
        return 75, f"出来高増加 ({ratio:.1f}倍)"
    if ratio > 1.0:
        return 60, f"出来高やや増 ({ratio:.1f}倍)"
    if ratio > 0.7:
        return 45, f"出来高並 ({ratio:.1f}倍)"
    return 25, f"出来高低調 ({ratio:.1f}倍)"


def score_momentum(close: pd.Series) -> tuple[float, str]:
    """直近5日リターン"""
    if len(close) < 6:
        return 50, "モメンタム算出不能"
    ret_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100
    if ret_5d > 5:
        return 85, f"5日リターン +{ret_5d:.1f}%"
    if ret_5d > 2:
        return 70, f"5日リターン +{ret_5d:.1f}%"
    if ret_5d > -2:
        return 55, f"5日リターン {ret_5d:+.1f}%"
    if ret_5d > -5:
        return 35, f"5日リターン {ret_5d:.1f}%"
    return 15, f"5日リターン {ret_5d:.1f}%"


# =============================================================================
# 銘柄分析パイプライン
# =============================================================================

def analyze_ticker(ticker: str, df: pd.DataFrame) -> dict | None:
    """1銘柄を分析しスコア辞書を返す。失敗時はNone。"""
    if df is None or df.empty or len(df) < 30:
        return None

    close = df["Close"].dropna()
    volume = df["Volume"].fillna(0)
    if len(close) < 30:
        return None

    # 指標計算
    sma25 = calc_sma(close, 25)
    sma75 = calc_sma(close, 75)
    sma200 = calc_sma(close, 200)
    rsi = calc_rsi(close, 14)
    macd, sig, hist = calc_macd(close)
    bb_u, bb_m, bb_l = calc_bollinger(close, 20, 2)

    # スコアリング
    s_trend, n_trend = score_trend(close, sma25, sma75, sma200)
    s_rsi, n_rsi = score_rsi(rsi)
    s_macd, n_macd = score_macd(macd, sig, hist)
    s_bb, n_bb = score_bollinger(close, bb_u, bb_m, bb_l)
    s_vol, n_vol = score_volume(volume)
    s_mom, n_mom = score_momentum(close)

    # 重み付き総合スコア
    total = (
        s_trend * SCORE_WEIGHTS["trend"]
        + s_rsi * SCORE_WEIGHTS["rsi"]
        + s_macd * SCORE_WEIGHTS["macd"]
        + s_bb * SCORE_WEIGHTS["bollinger"]
        + s_vol * SCORE_WEIGHTS["volume"]
        + s_mom * SCORE_WEIGHTS["momentum"]
    ) / sum(SCORE_WEIGHTS.values())

    current_price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) >= 2 else current_price
    change_pct = (current_price / prev_close - 1) * 100 if prev_close != 0 else 0

    avg_volume_20d = float(volume.iloc[-20:].mean()) if len(volume) >= 20 else float(volume.mean())
    turnover_jpy = current_price * avg_volume_20d  # 概算売買代金 (USD/JPYは別途換算が必要だが相対比較用)

    return {
        "ticker": ticker,
        "price": round(current_price, 2),
        "change_pct": round(change_pct, 2),
        "avg_volume_20d": int(avg_volume_20d),
        "turnover_proxy": int(turnover_jpy),
        "total_score": round(total, 1),
        "indicators": {
            "rsi": round(float(rsi.iloc[-1]), 1) if not pd.isna(rsi.iloc[-1]) else None,
            "sma25": round(float(sma25.iloc[-1]), 2) if not pd.isna(sma25.iloc[-1]) else None,
            "sma75": round(float(sma75.iloc[-1]), 2) if not pd.isna(sma75.iloc[-1]) else None,
            "macd_hist": round(float(hist.iloc[-1]), 3) if not pd.isna(hist.iloc[-1]) else None,
            "bb_upper": round(float(bb_u.iloc[-1]), 2) if not pd.isna(bb_u.iloc[-1]) else None,
            "bb_lower": round(float(bb_l.iloc[-1]), 2) if not pd.isna(bb_l.iloc[-1]) else None,
        },
        "scores": {
            "trend": s_trend,
            "rsi": s_rsi,
            "macd": s_macd,
            "bollinger": s_bb,
            "volume": s_vol,
            "momentum": s_mom,
        },
        "notes": {
            "trend": n_trend,
            "rsi": n_rsi,
            "macd": n_macd,
            "bollinger": n_bb,
            "volume": n_vol,
            "momentum": n_mom,
        },
    }


def fetch_universe(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """yfinanceで一括ダウンロード。レート制限対策で1回でまとめて取得。"""
    print(f"  Fetching {len(tickers)} tickers...", flush=True)
    data = yf.download(
        tickers,
        period=f"{LOOKBACK_DAYS}d",
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    result = {}
    for t in tickers:
        try:
            if len(tickers) == 1:
                df = data
            else:
                df = data[t] if t in data.columns.get_level_values(0) else None
            if df is not None and not df.empty:
                result[t] = df
        except Exception as e:
            print(f"  ! {t}: {e}", flush=True)
    return result


def run_analysis(universe: list[str], market_label: str) -> list[dict]:
    """ユニバース全体を分析し、出来高フィルタ後の銘柄リストを返す。"""
    print(f"[{market_label}] Starting analysis...", flush=True)
    raw = fetch_universe(universe)
    print(f"[{market_label}] Got data for {len(raw)}/{len(universe)} tickers", flush=True)

    results = []
    for ticker, df in raw.items():
        res = analyze_ticker(ticker, df)
        if res is None:
            continue
        res["market"] = market_label
        results.append(res)

    # 売買代金プロキシで上位50%に絞る (出来高動的抽出)
    if len(results) >= 4:
        results.sort(key=lambda x: x["turnover_proxy"], reverse=True)
        cutoff = max(len(results) // 2, TOP_N)
        results = results[:cutoff]

    print(f"[{market_label}] After volume filter: {len(results)} tickers", flush=True)
    return results


# =============================================================================
# メイン
# =============================================================================

def main():
    out_dir = Path(__file__).parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst)

    jp_results = run_analysis(JP_UNIVERSE, "JP")
    us_results = run_analysis(US_UNIVERSE, "US")

    # スコア降順でソート
    jp_results.sort(key=lambda x: x["total_score"], reverse=True)
    us_results.sort(key=lambda x: x["total_score"], reverse=True)

    payload = {
        "generated_at": now_jst.isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "weights": SCORE_WEIGHTS,
        "top_n": TOP_N,
        "markets": {
            "JP": {
                "top": jp_results[:TOP_N],
                "all_scanned": len(jp_results),
            },
            "US": {
                "top": us_results[:TOP_N],
                "all_scanned": len(us_results),
            },
        },
        "disclaimer": (
            "本データはテクニカル指標のみに基づく機械的なスコアリング結果であり、"
            "投資推奨ではありません。投資判断はご自身の責任で行ってください。"
        ),
    }

    out_path = out_dir / "recommendations.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Saved: {out_path}", flush=True)
    print(f"  JP top: {[r['ticker'] for r in jp_results[:5]]}", flush=True)
    print(f"  US top: {[r['ticker'] for r in us_results[:5]]}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
