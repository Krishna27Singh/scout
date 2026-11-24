from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class RepoTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    owner: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    priority: int = Field(default=100, ge=1)
    program_tags: list[str] = Field(default_factory=list)

    @field_validator("owner", "name")
    @classmethod
    def validate_component(cls, value: str) -> str:
        if "/" in value or value.strip() != value:
            raise ValueError("repository owner and name must be path components")
        return value

    @field_validator("program_tags")
    @classmethod
    def normalize_program_tags(cls, value: list[str]) -> list[str]:
        return sorted({tag.strip().casefold() for tag in value if tag.strip()})

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


class OrganizationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    org: str = Field(min_length=1, max_length=128)
    max_repos: int = Field(default=2, ge=1, le=100)
    priority: int = Field(default=100, ge=1)
    program_tags: list[str] = Field(default_factory=list)

    @field_validator("org")
    @classmethod
    def validate_organization(cls, value: str) -> str:
        if "/" in value or value.strip() != value:
            raise ValueError("organization must be a path component")
        return value

    @field_validator("program_tags")
    @classmethod
    def normalize_program_tags(cls, value: list[str]) -> list[str]:
        return sorted({tag.strip().casefold() for tag in value if tag.strip()})


class SeedCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    repositories: list[RepoTarget]
    organizations: list[OrganizationTarget] = Field(default_factory=list)


def load_seed_catalog(path: Path) -> SeedCatalog:
    try:
        with path.open(encoding="utf-8") as seed_file:
            payload = yaml.safe_load(seed_file)
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Unable to read valid seed repository file: {path}") from exc
    try:
        return SeedCatalog.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Invalid seed catalog in {path}: {exc}") from exc


def load_seed_repos(path: Path) -> list[RepoTarget]:
    """Load the catalog's explicit repository targets."""
    return load_seed_catalog(path).repositories


def merge_repo_targets(targets: list[RepoTarget]) -> list[RepoTarget]:
    merged: dict[tuple[str, str], RepoTarget] = {}
    for target in targets:
        key = (target.owner.casefold(), target.name.casefold())
        previous = merged.get(key)
        if previous is None:
            merged[key] = target
            continue
        preferred = target if target.priority < previous.priority else previous
        tags = sorted(set(previous.program_tags) | set(target.program_tags))
        merged[key] = preferred.model_copy(
            update={"priority": min(target.priority, previous.priority), "program_tags": tags}
        )
    return sorted(
        merged.values(),
        key=lambda target: (target.priority, target.owner.casefold(), target.name.casefold()),
    )
