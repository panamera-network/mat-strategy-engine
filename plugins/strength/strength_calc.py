import json
import pandas as pd

def calculate_strength(df: pd.DataFrame) -> pd.DataFrame:
    """
    Example strength calculation based on OHLC data.
    You can replace this with your real logic.
    """
    df['strength'] = (df['close'] - df['open']) / (df['high'] - df['low'] + 1e-9)
    return df

def run_strategy(file_path: str):
    """
    Entry point for the strength strategy plugin.
    Reads OHLC data from JSON, calculates strength, and prints results.
    """
    try:
        with open(file_path, 'r') as f:
            raw_data = json.load(f)
        df = pd.DataFrame(raw_data)

        print(f"✅ Loaded {len(df)} OHLC entries from {file_path}")
        result_df = calculate_strength(df)

        print("\n📊 Strength Results (first 5 rows):")
        print(result_df[['timestamp', 'open', 'high', 'low', 'close', 'strength']].head())

    except Exception as e:
        print(f"❌ Error running strategy: {e}")
