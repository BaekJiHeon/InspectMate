from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Decision = Literal["normal", "defect_suspected", "uncertain"]
Method = Literal["vlm_only", "vlm_reference", "patchcore", "patchcore_vlm"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Observation(StrictModel):
    image_id: str
    location: str
    fact: str
    reference_id: str | None


class VLMResult(StrictModel):
    decision: Decision
    summary: str
    observations: list[Observation]
    uncertainties: list[str]
    recommended_action: str


class QuestionResult(StrictModel):
    answer: str
    uncertainties: list[str]


class InspectionRequest(StrictModel):
    asset_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    category: str = Field("metal_nut", pattern=r"^[a-zA-Z0-9_]+$", max_length=64)
    method: Method = "vlm_reference"
    provider: Literal["openai", "demo"] = "openai"
    external_consent: bool = False
    use_cache: bool = True


class QuestionRequest(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    external_consent: bool = False


class ReviewRequest(StrictModel):
    status: Literal["unreviewed", "reviewed", "needs_followup"]
    note: str = Field("", max_length=5000)
    observation_exists: bool | None = None
    location_matches: bool | None = None
    unsupported_cause: bool | None = None
    uncertainty_appropriate: bool | None = None


class ExperimentRequest(StrictModel):
    category: str = Field("metal_nut", pattern=r"^[a-zA-Z0-9_]+$", max_length=64)
    methods: list[Method] = Field(default_factory=lambda: ["vlm_only", "vlm_reference"], min_length=1)
    sample_limit: int = Field(10, ge=1, le=10000)
    full_evaluation: bool = False
    exploratory: bool = True
    external_consent: bool = False
    use_cache: bool = False
