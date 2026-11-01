"""Model API keys from the macOS Keychain, with an expiry date and a rotation routine.

The key never lives in a file in the repo. At startup the app asks the Keychain for
it, checks the expiry date stored beside it, and refuses to run once that date has
passed. ``.env.local`` still works as a fallback for readers who are not on a Mac.

Command line (also wrapped by ``make key-status``, ``make key-set`` and ``make rotate-key``):

    python -m agent_observability.keys status
    python -m agent_observability.keys set --expires 2027-01-31
    python -m agent_observability.keys rotate --expires 2027-01-31
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

SERVICE = "agent-observability"
ACCOUNT = "llm-api-key"
SECURITY = "/usr/bin/security"  # absolute path: a planted `security` earlier in PATH is ignored
WARN_DAYS = 14
MAX_LIFETIME_DAYS = 90
LOCAL_PLACEHOLDER = "not-needed"
AUDIT_LOG = Path(".run/key-audit.log")

Runner = Callable[..., subprocess.CompletedProcess[str]]


class KeyExpiredError(RuntimeError):
    """The stored key is past its expiry date; rotate it before starting."""


class KeyMissingError(RuntimeError):
    """A Keychain service is configured but holds no key."""


@dataclass(frozen=True)
class KeySource:
    """Where to look, as in Lantern: an override variable, then one Keychain item.

    With ``keychain_service`` set (for example ``anthropic`` or ``nvidia``) the item is
    that service with your macOS user as the account, so one key serves every project
    that follows the same convention. Without it, the item is agent-observability's own.
    """

    keychain_service: str | None = None
    api_key_env: str | None = None

    @property
    def item(self) -> tuple[str, str]:
        if self.keychain_service:
            return self.keychain_service, os.environ.get("USER") or getpass.getuser()
        return SERVICE, ACCOUNT


OWN_ITEM = KeySource()


@dataclass(frozen=True)
class StoredKey:
    secret: str
    expires: date | None
    source: str  # "keychain", "env" or "none"


def fingerprint(secret: str) -> str:
    """A short, non-reversible label for logs: never print or log the key itself."""
    return hashlib.sha256(secret.encode()).hexdigest()[:8]


def keychain_available() -> bool:
    return sys.platform == "darwin" and os.path.exists(SECURITY)


def _run(
    runner: Runner, args: Sequence[str], stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return runner(list(args), input=stdin, capture_output=True, text=True, check=False)


def read_keychain(
    account: str = ACCOUNT, *, service: str = SERVICE, runner: Runner = subprocess.run
) -> StoredKey | None:
    found = _run(runner, [SECURITY, "find-generic-password", "-s", service, "-a", account, "-w"])
    secret = found.stdout.strip()  # never print stdout or stderr: either may hold the key
    if found.returncode != 0 or not secret:
        return None
    attributes = _run(runner, [SECURITY, "find-generic-password", "-s", service, "-a", account])
    return StoredKey(secret, parse_expiry(attributes.stdout), f"keychain:{service}")


def parse_expiry(attributes: str) -> date | None:
    """The expiry lives in the item's comment as ``expires=YYYY-MM-DD``."""
    match = re.search(r'"icmt"<blob>="[^"]*expires=(\d{4}-\d{2}-\d{2})', attributes)
    return date.fromisoformat(match.group(1)) if match else None


def write_keychain(
    secret: str,
    expires: date,
    account: str = ACCOUNT,
    *,
    service: str = SERVICE,
    runner: Runner = subprocess.run,
) -> None:
    """Store via ``security -i`` on stdin so the key never appears in the process list."""
    if not secret or any(c in secret for c in '"\\\n\r') or secret != secret.strip():
        raise ValueError("Key is empty or contains quotes, backslashes or whitespace.")
    command = (
        f'add-generic-password -U -s "{service}" -a "{account}" '
        f'-l "agent-observability model API key" -j "expires={expires.isoformat()}" -w "{secret}"\n'
    )
    result = _run(runner, [SECURITY, "-i"], stdin=command)
    if result.returncode != 0:
        raise RuntimeError(f"Keychain write failed: {result.stderr.strip()}")


def delete_keychain(
    account: str, *, service: str = SERVICE, runner: Runner = subprocess.run
) -> None:
    _run(runner, [SECURITY, "delete-generic-password", "-s", service, "-a", account])


def check_expiry(key: StoredKey, today: date | None = None) -> str | None:
    """Raise once expired; return a warning when close to expiry or when no date is set."""
    if key.secret in ("", LOCAL_PLACEHOLDER):
        return None  # Local model servers need no key, so there is nothing to expire.
    today = today or date.today()
    if key.expires is None:
        return (
            f"API key ({key.source}) has no expiry date. Set "
            "AGENT_OBSERVABILITY_LLM_API_KEY_EXPIRES, or run make key-set EXPIRES=YYYY-MM-DD."
        )
    if key.expires < today:
        raise KeyExpiredError(
            f"API key {fingerprint(key.secret)} expired on {key.expires}. Run make rotate-key."
        )
    days = (key.expires - today).days
    return (
        f"API key expires in {days} days ({key.expires}). Rotate it soon."
        if days <= WARN_DAYS
        else None
    )


def resolve(
    env_secret: str,
    env_expires: date | None,
    source: KeySource = OWN_ITEM,
    *,
    runner: Runner = subprocess.run,
) -> StoredKey:
    """Override variable, then the Keychain item, then the .env key, then the placeholder."""
    if source.api_key_env and (value := os.environ.get(source.api_key_env)):
        return StoredKey(value, env_expires, f"env:{source.api_key_env}")
    service, account = source.item
    if keychain_available():
        if stored := read_keychain(account, service=service, runner=runner):
            # Items made outside this repo (as in Lantern) carry no date; .env can supply one.
            return (
                stored if stored.expires else StoredKey(stored.secret, env_expires, stored.source)
            )
        if source.keychain_service:
            raise KeyMissingError(
                f"No key in the Keychain for service '{service}', account '{account}'. "
                f'Add it with: security add-generic-password -s {service} -a "$USER" -w'
            )
    if env_secret and env_secret != LOCAL_PLACEHOLDER:
        return StoredKey(env_secret, env_expires, "env")
    return StoredKey(LOCAL_PLACEHOLDER, None, "none")


def load_api_key(
    env_secret: str,
    env_expires: date | None,
    source: KeySource = OWN_ITEM,
    *,
    warn: Callable[[str], None] | None = None,
) -> str:
    key = resolve(env_secret, env_expires, source)
    if message := check_expiry(key):
        (warn or (lambda text: print(f"warning: {text}", file=sys.stderr)))(message)
    return key.secret


def validate_expiry(expires: date, today: date | None = None) -> date:
    today = today or date.today()
    if expires <= today:
        raise ValueError("Expiry must be in the future.")
    if expires > today + timedelta(days=MAX_LIFETIME_DAYS):
        raise ValueError(
            f"Expiry must be within {MAX_LIFETIME_DAYS} days; short-lived keys limit a leak."
        )
    return expires


def verify(base_url: str, secret: str, timeout: float = 5.0) -> bool:
    """A key works if the endpoint lists models with it."""
    headers = {"Authorization": f"Bearer {secret}"}
    if urllib.parse.urlsplit(base_url).hostname == "api.anthropic.com":
        headers["anthropic-version"] = "2023-06-01"  # /models there is Anthropic's own API
    request = urllib.request.Request(base_url.rstrip("/") + "/models", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            status: int = response.status
            return 200 <= status < 300
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def audit(action: str, secret: str, detail: str = "") -> None:
    """Append-only trail of key changes: fingerprints and dates only, never the key."""
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    with AUDIT_LOG.open("a") as log:
        log.write(f"{stamp} {action} key={fingerprint(secret)} {detail}".rstrip() + "\n")


def _prompt_secret(label: str) -> str:
    return getpass.getpass(f"Paste the {label} (input hidden): ").strip()


def _require_keychain() -> None:
    if not keychain_available():
        raise SystemExit(
            "The macOS Keychain is not available here; set the key in .env.local instead."
        )


def _configured() -> tuple[KeySource, str, date | None, str]:
    from agent_observability.config import key_source, settings

    env = settings.llm_api_key.get_secret_value()
    return key_source(), env, settings.llm_api_key_expires, settings.llm_base_url


def cmd_status(_: argparse.Namespace) -> int:
    source, env, env_expires, _url = _configured()
    try:
        key = resolve(env, env_expires, source)
    except KeyMissingError as exc:
        print(f"MISSING: {exc}")
        return 1
    if key.source == "none":
        print("No API key configured; fine for a local model server.")
        return 0
    print(f"source={key.source} key={fingerprint(key.secret)} expires={key.expires or 'not set'}")
    try:
        message = check_expiry(key)
    except KeyExpiredError as exc:
        print(f"EXPIRED: {exc}")
        return 1
    print(message or "OK")
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    _require_keychain()
    service, account = _configured()[0].item
    expires = validate_expiry(args.expires)
    secret = _prompt_secret("API key")
    write_keychain(secret, expires, account, service=service)
    audit("set", secret, f"service={service} expires={expires}")
    print(f"Stored key {fingerprint(secret)} in Keychain service '{service}', expiring {expires}.")
    return 0


def cmd_rotate(args: argparse.Namespace) -> int:
    """Create replacement, switch the app to it, verify, then revoke the old one."""
    _require_keychain()
    source, _env, _expires, base_url = _configured()
    service, account = source.item
    staging = f"{account}.next"
    expires = validate_expiry(args.expires)
    old = read_keychain(account, service=service)
    print("Step 1/4: create a new key in your provider's console with an expiry date.")
    secret = _prompt_secret("new API key")
    write_keychain(secret, expires, staging, service=service)
    print("Step 2/4: verifying the new key against", base_url)
    if not verify(base_url, secret):
        delete_keychain(staging, service=service)
        audit("rotate-failed", secret, f"service={service}")
        print("The new key did not work. Nothing changed; the old key is still active.")
        return 1
    print("Step 3/4: switching the app to the new key.")
    write_keychain(secret, expires, account, service=service)
    delete_keychain(staging, service=service)
    replaced = fingerprint(old.secret) if old else "none"
    audit("rotate", secret, f"service={service} expires={expires} replaces={replaced}")
    print("Step 4/4: restart with make down && make up, then revoke the old key", end=" ")
    print(f"({fingerprint(old.secret)})" if old else "", "in your provider's console.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent_observability.keys")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show where the key comes from and when it expires")
    for name, help_text in (
        ("set", "store a key with an expiry date"),
        ("rotate", "replace the key safely"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--expires", type=date.fromisoformat, required=True, help="YYYY-MM-DD")
    args = parser.parse_args(argv)
    handlers = {"status": cmd_status, "set": cmd_set, "rotate": cmd_rotate}
    try:
        return handlers[args.command](args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyMissingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
