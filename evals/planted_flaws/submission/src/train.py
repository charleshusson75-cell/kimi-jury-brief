"""Train the model and report the validation Brier score."""
import joblib
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss
from sklearn.model_selection import train_test_split

from config import RANDOM_STATE
from src.data import build_target, load
from src.features import add_features, feature_columns


def main():
    env, corr, _ = load()
    df = build_target(add_features(env), corr)
    X, y = df[feature_columns(df)], df["corrosion"]

    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=RANDOM_STATE)

    model = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.05, random_state=RANDOM_STATE)
    model.fit(X_train, y_train)

    proba = model.predict_proba(X_val)[:, 1]
    print(f"Validation Brier score: {brier_score_loss(y_val, proba):.3f}")
    joblib.dump(model, "model.joblib")


if __name__ == "__main__":
    main()
