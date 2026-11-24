import json
import tomllib
from pathlib import Path

import yaml

from app._version import __version__

ROOT = Path(__file__).resolve().parents[2]


def test_release_configuration_and_project_versions_are_consistent() -> None:
    release_config = json.loads((ROOT / "release-please-config.json").read_text())
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependabot = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    workflow = yaml.safe_load((ROOT / ".github/workflows/release-please.yml").read_text())

    version = manifest["."]
    assert version == pyproject["project"]["version"] == __version__
    assert release_config["release-type"] == "python"
    assert release_config["packages"]["."]["package-name"] == "scout"
    assert release_config["changelog-path"] == "CHANGELOG.md"
    assert release_config["bump-minor-pre-major"] is True
    assert release_config["bump-patch-for-minor-pre-major"] is True
    assert any(
        entry["path"] == "backend/app/_version.py" for entry in release_config["extra-files"]
    )
    assert len(release_config["packages"]) == 1
    assert len(dependabot["updates"]) == 2
    assert all(update["schedule"]["interval"] == "weekly" for update in dependabot["updates"])
    assert all(update["open-pull-requests-limit"] == 5 for update in dependabot["updates"])
    assert workflow["jobs"]["release-please"]["steps"][0]["uses"] == (
        "googleapis/release-please-action@v5"
    )
