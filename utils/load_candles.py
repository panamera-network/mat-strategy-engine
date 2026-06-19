# utils/load_candles.py

import csv

from mt5.fetcher import Candle


def load_candles_from_csv(path: str) -> list[Candle]:
    with open(path, newline='') as f:
        reader = csv.DictReader(f, delimiter='\t')
        candles = []
        for row in reader:
            candles.append(Candle(
                date=row["<DATE>"],
                time=row["<TIME>"],
                open=float(row["<OPEN>"]),
                high=float(row["<HIGH>"]),
                low=float(row["<LOW>"]),
                close=float(row["<CLOSE>"]),
                tickvol=int(row["<TICKVOL>"]),
                vol=int(row["<VOL>"]),
                spread=int(row["<SPREAD>"])
            ))
        return candles
