"""Dry-run with synthetic data to validate scoring logic without network."""
import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from analyze import analyze_ticker, SCORE_WEIGHTS, TOP_N

np.random.seed(42)

def make_synthetic_df(trend: float, vol: float, n: int = 200) -> pd.DataFrame:
    """Generate synthetic OHLCV with given trend (per-day drift) and volatility."""
    dates = pd.date_range(end=datetime.now(), periods=n, freq="B")
    returns = np.random.normal(trend, vol, n)
    price = 1000 * np.exp(np.cumsum(returns))
    high = price * (1 + np.abs(np.random.normal(0, 0.01, n)))
    low = price * (1 - np.abs(np.random.normal(0, 0.01, n)))
    open_ = price * (1 + np.random.normal(0, 0.005, n))
    volume = np.random.randint(1_000_000, 5_000_000, n)
    return pd.DataFrame({
        "Open": open_, "High": high, "Low": low,
        "Close": price, "Volume": volume,
    }, index=dates)


# Test cases with different trend characteristics
test_cases = {
    "STRONG_UP":   (0.005, 0.015),   # 強い上昇トレンド
    "MILD_UP":     (0.002, 0.012),   # 緩やかな上昇
    "FLAT":        (0.000, 0.012),   # 横ばい
    "DOWNTREND":   (-0.003, 0.015),  # 下降トレンド
    "VOLATILE":    (0.001, 0.030),   # 高ボラ・横ばい
    "RECOVERY":    (0.0, 0.020),     # オーバーソールドからの反発期待用は別途
}

results = []
for name, (trend, vol) in test_cases.items():
    df = make_synthetic_df(trend, vol)
    res = analyze_ticker(name, df)
    if res:
        res["market"] = "TEST"
        results.append(res)

results.sort(key=lambda x: x["total_score"], reverse=True)

print("=" * 70)
print("DRY RUN RESULTS (synthetic data)")
print("=" * 70)
for r in results:
    print(f"\n{r['ticker']:12s}  score={r['total_score']:5.1f}  price={r['price']:.2f}  chg={r['change_pct']:+.2f}%")
    for key in ["trend", "rsi", "macd", "bollinger", "volume", "momentum"]:
        print(f"  {key:11s}: {r['scores'][key]:5.1f}  {r['notes'][key]}")

print("\n" + "=" * 70)
print("Logic validation:")
strong = next((r for r in results if r["ticker"] == "STRONG_UP"), None)
down   = next((r for r in results if r["ticker"] == "DOWNTREND"), None)
if strong and down:
    if strong["total_score"] > down["total_score"]:
        print(f"  ✓ STRONG_UP ({strong['total_score']}) > DOWNTREND ({down['total_score']})")
    else:
        print(f"  ✗ Logic issue: STRONG_UP={strong['total_score']}, DOWN={down['total_score']}")
print("=" * 70)
