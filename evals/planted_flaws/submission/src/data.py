"""Load the Kaggle files and build the training target with the Airbus convention."""
import pandas as pd

from config import DATA_DIR


def load():
    env = pd.read_csv(f"{DATA_DIR}/environment_training.csv")
    corr = pd.read_csv(f"{DATA_DIR}/corrosions_training.csv", parse_dates=["observation_date"])
    test = pd.read_csv(f"{DATA_DIR}/environment_test.csv")
    return env, corr, test


def build_target(env: pd.DataFrame, corr: pd.DataFrame) -> pd.DataFrame:
    """One positive row (observation month) and one negative row (24 months earlier) per aircraft."""
    obs = corr[["aircraft_id", "observation_date"]].copy()
    pos = obs.assign(year_month=obs["observation_date"].dt.to_period("M").astype(str), corrosion=1)
    neg = obs.assign(
        year_month=(obs["observation_date"] - pd.DateOffset(months=24)).dt.to_period("M").astype(str),
        corrosion=0,
    )
    pairs = pd.concat([pos, neg])[["aircraft_id", "year_month", "corrosion"]]
    return env.merge(pairs, on=["aircraft_id", "year_month"], how="inner")
