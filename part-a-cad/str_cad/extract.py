import json
import os

from google import genai
from pydantic import BaseModel

from str_cad.schema import STRParams


class STRExtractionTank(BaseModel):
    diameter_m: float
    height_m: float
    bottom: str


class STRExtractionLiquid(BaseModel):
    height_m: float


class STRExtractionBaffles(BaseModel):
    count: int
    width_m: float
    height_m: float
    arrangement: str


class STRExtractionShaft(BaseModel):
    central: bool


class STRExtractionImpellers(BaseModel):
    count: int
    type: str
    blades: int
    diameter_ratio: float
    blade_height_m: float | None
    blade_length_m: float | None
    lowest_clearance_m: float
    inter_impeller_clearance_m: float


class STRExtraction(BaseModel):
    family: str
    tank: STRExtractionTank
    liquid: STRExtractionLiquid
    baffles: STRExtractionBaffles
    shaft: STRExtractionShaft
    impellers: STRExtractionImpellers


SYSTEM = """Extract stirred-tank-reactor geometry into the provided schema.
All lengths must be in meters.
The family is always "stirred_tank_reactor".
Set impellers.type to "rushton".
If diameter_ratio is omitted, use 1/3.
If blade_length_m or blade_height_m is omitted, leave it null; downstream validation fills D/4 and D/5.
Infer counts from the description.
"""


def extract_str_params(
    prompt: str,
    api_key: str | None = None,
    model: str = "gemini-2.5-flash",
) -> STRParams:
    key = api_key or os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "system_instruction": SYSTEM,
            "response_mime_type": "application/json",
            "response_schema": STRExtraction,
        },
    )
    data = json.loads(resp.text)
    return STRParams.model_validate(data)
