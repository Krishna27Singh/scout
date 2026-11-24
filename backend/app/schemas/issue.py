from pydantic import BaseModel, ConfigDict, Field


class IssueSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    repository: str
    number: int
    title: str
    body: str | None = None
    html_url: str
    labels: list[str] = Field(default_factory=list)
    state: str


class MatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue: IssueSummary
    score: float
    reasons: list[str] = Field(default_factory=list)


class ScoutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    matches: list[MatchResult] = Field(default_factory=list)
