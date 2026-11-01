"""One switch picks the endpoint, model, key source and allowlist; nothing secret in the file."""

from datetime import date
from pathlib import Path

import pytest

from agent_observability import profiles

REPO = Path(__file__).parents[1]


def test_shipped_profiles_load_and_hold_no_secrets():
    loaded = profiles.load((REPO / "models.toml",))
    assert {"local", "haiku", "muse", "nemotron"} <= set(loaded)
    text = (REPO / "models.toml").read_text()
    assert "sk-" not in text and "nvapi-" not in text


def test_hosted_profile_sets_everything_and_allowlists_its_own_host():
    loaded = profiles.load((REPO / "models.toml",))
    update = profiles.updates("haiku", "pypi.org", loaded)
    assert update["llm_base_url"] == "https://api.anthropic.com/v1"
    assert update["llm_model"] == "claude-haiku-5-5"
    assert update["llm_keychain_service"] == "anthropic"
    assert update["llm_temperature"] is None  # omitted for Claude
    assert update["allowed_hosts"] == "pypi.org,api.anthropic.com"


def test_local_profile_needs_no_allowlist_or_key():
    update = profiles.updates("local", "", profiles.load((REPO / "models.toml",)))
    assert "allowed_hosts" not in update and update["llm_keychain_service"] is None


def test_local_file_overrides_and_adds(tmp_path):
    shared = tmp_path / "models.toml"
    shared.write_text(
        '[muse]\nbase_url = "https://integrate.api.nvidia.com/v1"\nmodel = "REPLACE"\n'
    )
    personal = tmp_path / "models.local.toml"
    personal.write_text('[muse]\nmodel = "vendor/muse-30b"\nkey_expires = 2027-01-31\n')
    update = profiles.updates("muse", "", profiles.load((shared, personal)))
    assert update["llm_model"] == "vendor/muse-30b"
    assert update["llm_api_key_expires"] == date(2027, 1, 31)


@pytest.mark.parametrize(
    "toml, name, message",
    [
        ('[a]\nbase_url = "http://localhost/v1"\nmodel = "m"\n', "b", "Choose one of: a"),
        ('[a]\nbase_url = "x"\nmodel = "REPLACE-me"\n', "a", "no model id yet"),
        ('[a]\nmodel = "m"\n', "a", "needs both"),
        ('[a]\nbase_url = "x"\nmodel = "m"\napi_key = "sk-1"\n', "a", "unknown keys"),
    ],
)
def test_bad_profiles_fail_with_a_clear_message(tmp_path, toml, name, message):
    path = tmp_path / "models.toml"
    path.write_text(toml)
    with pytest.raises(profiles.ProfileError, match=message):
        profiles.updates(name, "", profiles.load((path,)))
