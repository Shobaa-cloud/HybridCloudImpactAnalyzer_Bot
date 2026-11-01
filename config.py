import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///local.db")

    ENABLE_AWS_ENRICHMENT = os.getenv("ENABLE_AWS_ENRICHMENT", "false").lower() == "true"
    AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

    # Confidence score is capped below 100 -- the tool should never claim
    # false certainty about a heuristic risk estimate.
    MAX_CONFIDENCE_SCORE = 97
    BASE_CONFIDENCE_SCORE = 55
