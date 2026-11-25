"""Ask IBM Granite on watsonx.ai for feature ideas."""
from ibm_watsonx_ai import Credentials
from ibm_watsonx_ai.foundation_models import ModelInference

from config import WATSONX_APIKEY, WATSONX_PROJECT_ID, WATSONX_URL


def suggest_features(columns: list[str]) -> str:
    model = ModelInference(
        model_id="ibm/granite-3-8b-instruct",
        credentials=Credentials(url=WATSONX_URL, api_key=WATSONX_APIKEY),
        project_id=WATSONX_PROJECT_ID,
    )
    prompt = "Suggest engineered features for predicting aircraft wing corrosion from: " + ", ".join(columns)
    return model.generate_text(prompt=prompt)
