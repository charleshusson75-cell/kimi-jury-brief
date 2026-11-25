# Team Salt & Pepper: Wing Corrosion Digital Twin ✈️

HAKS 2026 submission. We predict, for every aircraft and month, the probability that corrosion would be found at inspection.

## Results
- **Brier score 0.071** on validation (5-fold **GroupKFold by aircraft**, so no aircraft appears in both train and validation)
- Public leaderboard: 0.083

## Approach
1. **Target**: Airbus convention. Month of first observed corrosion = 1, the month 24 months earlier = 0 (`src/data.py`).
2. **Features**: monthly ground environment plus 12-month rolling exposure (sea salt, humidity, parking time) (`src/features.py`).
3. **Model**: gradient boosting, **calibrated with isotonic regression** so probabilities are reliable for the Brier score.
4. **IBM watsonx.ai**: we used IBM Granite on watsonx.ai to generate and rank feature ideas (`src/watsonx_features.py`).

## What we learned about corrosion
Our **SHAP analysis** shows that **sea-salt exposure while parked** is the #1 driver of corrosion, ahead of humidity: aircraft based at coastal airports corrode about 3x faster.

## Run
```bash
pip install -r requirements.txt
python -m src.train      # trains and prints the validation Brier score
python -m src.predict    # writes submission.csv
```
Data: put the Kaggle CSVs in `data/`.
