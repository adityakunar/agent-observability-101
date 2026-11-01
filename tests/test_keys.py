"""Keys come from the Keychain, carry an expiry date, and never leak into argv or logs."""

import subprocess
from datetime import date

import pytest

from agent_observability import keys

ATTRIBUTES = """keychain: "/Users/q/Library/Keychains/login.keychain-db"
attributes:
    "acct"<blob>="llm-api-key"
    "icmt"<blob>="expires=2027-01-31"
    "svce"<blob>="agent-observability"
"""


class FakeSecurity:
    """Stands in for /usr/bin/security and records every call."""

    def __init__(self, items: dict[str, tuple[str, str]] | None = None) -> None:
        self.items = items or {}
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, args: list[str], *, input: str | None = None, **_: object):
        self.calls.append((args, input))
        if args[1] == "find-generic-password":
            account = args[args.index("-a") + 1]
            if account not in self.items:
                return subprocess.CompletedProcess(args, 44, "", "not found")
            secret, attributes = self.items[account]
            return subprocess.CompletedProcess(
                args, 0, secret + "\n" if "-w" in args else attributes, ""
            )
        return subprocess.CompletedProcess(args, 0, "", "")


def test_reads_secret_and_expiry_from_keychain():
    security = FakeSecurity({"llm-api-key": ("sk-live-123", ATTRIBUTES)})
    stored = keys.read_keychain(runner=security)
    assert stored == keys.StoredKey(
        "sk-live-123", date(2027, 1, 31), "keychain:agent-observability"
    )


def test_missing_keychain_item_is_none():
    assert keys.read_keychain(runner=FakeSecurity()) is None


def test_keychain_wins_over_env(monkeypatch):
    monkeypatch.setattr(keys, "keychain_available", lambda: True)
    security = FakeSecurity({"llm-api-key": ("sk-keychain", ATTRIBUTES)})
    assert keys.resolve("sk-env", None, runner=security).source == "keychain:agent-observability"


def test_env_fallback_and_local_placeholder(monkeypatch):
    monkeypatch.setattr(keys, "keychain_available", lambda: False)
    assert keys.resolve("sk-env", date(2027, 1, 1)).source == "env"
    assert keys.resolve("not-needed", None).source == "none"


def test_write_keeps_secret_out_of_argv():
    security = FakeSecurity()
    keys.write_keychain("sk-secret-value", date(2027, 1, 31), runner=security)
    args, stdin = security.calls[0]
    assert args == [keys.SECURITY, "-i"]
    assert "sk-secret-value" not in " ".join(args)
    assert stdin is not None and '-w "sk-secret-value"' in stdin and "expires=2027-01-31" in stdin


@pytest.mark.parametrize("bad", ["", 'has"quote', "back\\slash", "new\nline", " padded"])
def test_write_rejects_keys_that_could_break_quoting(bad):
    with pytest.raises(ValueError):
        keys.write_keychain(bad, date(2027, 1, 31), runner=FakeSecurity())


def test_expiry_checks():
    today = date(2026, 11, 1)
    fresh = keys.StoredKey("sk", date(2027, 1, 1), "keychain")
    soon = keys.StoredKey("sk", date(2026, 11, 10), "keychain")
    expired = keys.StoredKey("sk", date(2026, 10, 31), "keychain")
    assert keys.check_expiry(fresh, today) is None
    assert "expires in 9 days" in (keys.check_expiry(soon, today) or "")
    assert "no expiry date" in (keys.check_expiry(keys.StoredKey("sk", None, "env"), today) or "")
    assert keys.check_expiry(keys.StoredKey("not-needed", None, "none"), today) is None
    with pytest.raises(keys.KeyExpiredError) as error:
        keys.check_expiry(expired, today)
    assert "sk" not in str(error.value).replace(keys.fingerprint("sk"), "")


def test_new_keys_must_be_short_lived():
    today = date(2026, 11, 1)
    assert keys.validate_expiry(date(2027, 1, 30), today) == date(2027, 1, 30)
    for too_far_or_past in (date(2027, 6, 1), today):
        with pytest.raises(ValueError):
            keys.validate_expiry(too_far_or_past, today)


def test_audit_log_has_fingerprint_not_key(tmp_path, monkeypatch):
    monkeypatch.setattr(keys, "AUDIT_LOG", tmp_path / "audit.log")
    keys.audit("rotate", "sk-very-secret", "expires=2027-01-31")
    line = (tmp_path / "audit.log").read_text()
    assert "sk-very-secret" not in line
    assert keys.fingerprint("sk-very-secret") in line


LANTERN_STYLE = keys.KeySource(keychain_service="anthropic", api_key_env="ANTHROPIC_API_KEY")


def test_lantern_style_service_uses_your_user_as_account(monkeypatch):
    monkeypatch.setattr(keys, "keychain_available", lambda: True)
    monkeypatch.setenv("USER", "q")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    security = FakeSecurity({"q": ("sk-ant-123", "no comment")})
    stored = keys.resolve("not-needed", date(2027, 1, 31), LANTERN_STYLE, runner=security)
    assert stored.secret == "sk-ant-123" and stored.source == "keychain:anthropic"
    assert stored.expires == date(2027, 1, 31)  # item has no date; .env supplies it
    assert security.calls[0][0][2:6] == ["-s", "anthropic", "-a", "q"]


def test_override_variable_wins_when_set(monkeypatch):
    monkeypatch.setattr(keys, "keychain_available", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    security = FakeSecurity({"q": ("sk-ant-123", "")})
    stored = keys.resolve("not-needed", None, LANTERN_STYLE, runner=security)
    assert stored == keys.StoredKey("sk-from-env", None, "env:ANTHROPIC_API_KEY")
    assert security.calls == []


def test_configured_service_without_a_key_says_how_to_add_it(monkeypatch):
    monkeypatch.setattr(keys, "keychain_available", lambda: True)
    monkeypatch.setenv("USER", "q")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(keys.KeyMissingError, match="security add-generic-password -s anthropic"):
        keys.resolve("not-needed", None, LANTERN_STYLE, runner=FakeSecurity())
