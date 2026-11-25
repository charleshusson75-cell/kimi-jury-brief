"""Monthly environment + 12-month rolling exposure per aircraft."""
import pandas as pd

ROLLING = [
    "sea_salt_aerosol_05_5_mixing_ratio",
    "metar_relative_humidity",
    "total_parking_minutes",
    "sulphur_dioxide_mass_mixing_ratio",
]


def add_features(env: pd.DataFrame) -> pd.DataFrame:
    env = env.sort_values(["aircraft_id", "year_month"]).copy()
    for col in ROLLING:
        env[f"{col}_roll12"] = (
            env.groupby("aircraft_id")[col].transform(lambda s: s.rolling(12, min_periods=1).mean())
        )
    env["age_months"] = env.groupby("aircraft_id").cumcount()
    return env


def feature_columns(df: pd.DataFrame) -> list[str]:
    drop = {"aircraft_id", "year_month", "month_start_date", "corrosion"}
    return [c for c in df.columns if c not in drop]
