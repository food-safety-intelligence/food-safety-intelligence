"""Standard one-page DataFrame profile."""

from __future__ import annotations

import pandas as pd


def peek(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Print a compact profile of a DataFrame and return `df.head(3)`.

    Prints: shape, memory usage, columns, top-10 missingness. Returns head(3)
    so notebooks can display it inline as the cell's last expression.
    """
    print(f"=== {name} ===")
    print(f"shape:   {df.shape[0]:,} rows x {df.shape[1]} cols")
    print(f"memory:  {df.memory_usage(deep=True).sum() / 1e6:.1f} MB")
    print(f"columns: {list(df.columns)}")
    print("\n-- missing values (top 10) --")
    miss = df.isna().mean().sort_values(ascending=False).head(10)
    print((miss * 100).round(2).astype(str) + "%")
    print("\n-- head(3) --")
    return df.head(3)
