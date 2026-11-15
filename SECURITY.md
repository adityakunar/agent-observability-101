# Security: keys, network and the agent sandbox

This page is in Simplified Technical English (ASD-STE100). Short sentences. One
action per step. That is on purpose: you may read it at 2 a.m. with a leaked key.

## 1. Summary

| Item | Rule in this repo |
| --- | --- |
| Key storage | On macOS, the model API key is in the Keychain. The app reads it at startup. |
| Key expiry | Each key has an expiry date. The app warns 14 days before that date. After that date, the app does not start. |
| Key lifetime | A new key can have a maximum life of 90 days. |
| Key rotation | `make rotate-key` replaces the key in four steps. |
| Logs | Logs show an 8-character fingerprint of the key. Logs do not show the key. |
| Outbound traffic | The app sends the key only to a local model or to an allowlisted HTTPS host. |
| Inbound traffic | The server listens on `127.0.0.1` only. It refuses requests from other websites. |
| macOS sandbox | `make server-offline` and `make chat-offline` block all traffic that leaves the computer. |
| Local model server | `make model` starts rapid-mlx with telemetry, version check and web tools off. Run it as a second macOS user (3.6). |
| Leak scan | `make scan-secrets` scans the files and the git history with gitleaks. |
| Dependency scan | `make audit` compares each locked package with known vulnerabilities. `make verify` runs it. |

A local model does not need a key. If you use a local model, the app works with no key.

## 2. Keys

### 2.1 Store a key (macOS)

1. Get a key from your provider. Set an expiry date on it in the provider console.
2. Type `make key-set EXPIRES=YYYY-MM-DD`. Use the same date as in step 1.
3. Paste the key when the prompt shows. The screen does not show the key.
4. Type `make key-status`. Make sure that the output shows `source=keychain` and the correct date.

The Keychain item has the service name `agent-observability`. The expiry date is in
the comment of the item, as `expires=YYYY-MM-DD`.

NOTE: The Keychain does not make a key expire. A generic password has no expiry
field. The app reads the date and does the check itself (`src/agent_observability/keys.py`).

NOTE: Do not use `security add-generic-password -w <key>`. Other processes can see
command arguments in `ps`. This repo sends the key to `security -i` through stdin.

### 2.2 Use a key that is already in the Keychain (shared with other tools)

Some tools keep one Keychain item for each provider. The service name is the provider
(for example `anthropic` or `nvidia`). The account is your macOS user. This repo can
read the same item. Then one key serves all your projects.

1. If the key is not in the Keychain, type `security add-generic-password -s anthropic -a "$USER" -w`.
2. Paste the key when the prompt shows.
3. The `haiku` profile in `models.toml` reads this item. In `models.local.toml`, add
   only the expiry date of your key:

   ```toml
   [haiku]
   key_expires = "YYYY-MM-DD"
   ```

4. Type `make key-status PROFILE=haiku`. Make sure that the output shows `source=keychain:anthropic`.

For a different provider, add a full profile to `models.local.toml` with the same
fields as `haiku`. For NVIDIA, use `https://integrate.api.nvidia.com/v1` and the
service `nvidia`. `temperature = "omit"` removes the temperature from each request,
because newer Claude models refuse a low temperature. A profile allows its own host
for that run.

NOTE: A key that another tool stored has no expiry date in the Keychain. Put the date from the
provider console in `key_expires`. Then the expiry checks work.

To test a different key one time, set `AGENT_OBSERVABILITY_LLM_API_KEY_ENV=ANTHROPIC_API_KEY`.
When that variable has a value, the app uses it. When it is empty, the app reads the Keychain.

`make key-set` and `make rotate-key` also use the configured service.

The app calls `/usr/bin/security` with its full path. A program with the same name in
your `PATH` cannot take its place.

### 2.3 Switch between models (profiles)

`models.toml` has named profiles. Each profile sets the URL, the model, the Keychain
service and the allowed host. The file has no keys. The default profiles are:

| Profile | Model | Key |
| --- | --- | --- |
| `local` | Gemma on your Mac (`make model`) | None |
| `haiku` | `claude-haiku-5-5` on Anthropic | Keychain service `anthropic` |

To use a profile:

1. Make sure that the key is in the Keychain (section 2.2, step 1).
2. In one terminal, type `make server PROFILE=haiku`.
3. In a second terminal, type `make chat PROFILE=haiku`.

A hosted profile does not need `make model`.

The profile adds its own host to the allowlist for that run only. Other hosts stay blocked.
If you do not set `PROFILE`, `make` uses the `local` profile. Thus a hosted model runs only
when you name it. `make status` shows the model that the chat will use.

To add an expiry date or a personal profile, make the file `models.local.toml`. Git ignores it.
Example:

```toml
[haiku]
key_expires = 2027-01-31

[nvidia]
base_url = "https://integrate.api.nvidia.com/v1"
model = "<model id from build.nvidia.com>"
keychain_service = "nvidia"
key_expires = 2027-01-31
```

The app stops with a clear message if the profile name is wrong or the model id is missing.

### 2.4 Store a key (Linux or Windows)

1. Open `.env.local`. Do not commit this file. Git ignores it.
2. Add `AGENT_OBSERVABILITY_LLM_API_KEY=<key>`.
3. Add `AGENT_OBSERVABILITY_LLM_API_KEY_EXPIRES=YYYY-MM-DD`.

The app does the same expiry checks on this key.

### 2.5 Rotate a key

Do this procedure before the warning starts. Put a reminder in your calendar.

1. Make a new key in the provider console. Set an expiry date on it.
2. Type `make rotate-key EXPIRES=YYYY-MM-DD`.
3. Paste the new key when the prompt shows.
4. The script tests the new key on `<base_url>/models`.
   - If the test fails, the script deletes the new key. The old key stays active. Stop here.
   - If the test passes, the new key replaces the old key in the Keychain.
5. Stop `make server` and `make chat`. Then start them again.
6. Revoke the old key in the provider console. The script shows the fingerprint of the old key.

CAUTION: Do step 6 last. If you revoke the old key before the new key works, the app stops.

Each key change adds one line to `.run/key-audit.log`. The line has the date,
the action and the fingerprint. It does not have the key.

### 2.6 Make the rules strong

An expiry date helps only if a system enforces it. These controls are in order of strength:

1. Short-lived credentials (OIDC, STS). They expire after minutes. You do not rotate them.
2. A secrets manager with automatic rotation (AWS, GCP, Vault, 1Password).
3. A policy for the maximum life of a key, if your provider has one.
4. Push protection and gitleaks, in CI and before each commit.
5. Least privilege. Give each app or agent its own key with a small scope.

## 3. Network

All rules start from "deny". Then each task gets only the access that it needs.

### 3.1 Outbound traffic from the app

Before the app sends the key, it does a check of the model URL (`netpolicy.check_endpoint`):

- A local model (`localhost`, `127.0.0.1`, `::1`) is always permitted.
- Another host must use HTTPS.
- Another host must be in `AGENT_OBSERVABILITY_ALLOWED_HOSTS`.

A profile adds the host of its `base_url` to this list for that run. Example
`models.local.toml` for a hosted model:

```toml
[provider]
base_url = "https://api.your-provider.example/v1"
model = "your-tool-calling-model"
```

The check uses exact names. Thus `api.your-provider.example.evil.test` fails. If the
check fails, the app stops before it sends a request.

### 3.2 Inbound traffic to the server

The delivery desk and the MCP tools have no authentication. Thus only your computer must get access to them.

- The server listens on `127.0.0.1:8000`. Other computers cannot connect.
- The server refuses a request with 403 if the `Host` header is not a local name.
- The server refuses a request with 403 if the `Origin` header is another website.

NOTE: `127.0.0.1` does not stop your own browser. A website in a browser tab can
send requests to `http://localhost:8000`. With DNS rebinding, that website can also
read the replies. The `Host` and `Origin` checks (`netpolicy.LocalOnly`) stop this.
The MCP specification tells local HTTP servers to do these checks.

To see the checks, start the server. Then type these commands in a second terminal:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/desk/snapshot
# 200: a local request
curl -s -o /dev/null -w '%{http_code}\n' -H 'Origin: https://evil.example' http://localhost:8000/desk/snapshot
# 403: a request from another website
```

### 3.3 No outbound traffic (macOS sandbox)

The app checks cover only the app code. A library can open its own connection. The
macOS sandbox blocks all connections that leave the computer.

Use this procedure with a local model:

1. In terminal 1, type `make model`. The model runs outside the sandbox.
2. In terminal 2, type `make server-offline`.
3. In terminal 3, type `make chat-offline`.

The profile is `security/loopback-only.sb`. It also does these things:

- It permits writes only in the project folder and the uv cache.
- It blocks reads of `~/.ssh`, `~/.aws` and `~/.config/gcloud`.

### 3.4 Tidbit: Seatbelt only gets you so far

`sandbox-exec` uses Seatbelt, the macOS kernel sandbox. Apple uses it for Safari
and for App Store apps. It costs nothing and it starts at once. But it has five limits:

1. It filters by IP address, not by host name. It cannot permit only `api.openai.com`.
2. It has no limits for CPU, memory, processes or time.
3. The secret stays in the same process. A sandboxed agent can read its own key.
4. It does not reset. Changes stay on your disk after the run.
5. Apple marks `sandbox-exec` as deprecated. The profile language has no public documentation.

A container behind a filtering proxy can close each gap: a host allowlist, CPU and
memory caps, a key that stays in the proxy, and a disposable file system. This
chapter does not build one.

Use Seatbelt for fast local work with a local model. Use a stronger level (section 4)
when the code, the packages or the network are not under your control.

### 3.5 Tidbit: the model server phones home

`make model` starts rapid-mlx, a small server that runs Gemma on the Apple GPU. It is
a fast, single-maintainer project. Out of the box it does five things that a security
page must tell you about:

1. It sends usage telemetry to PostHog. This is on by default since version 0.15.0.
2. It checks for a new version on each start.
3. It downloads model weights from the project's own mirror first, then from Hugging Face.
   Each file is checked against the hashes that Hugging Face publishes, so Hugging Face stays the trust root.
4. Its chat mode has web tools. The model can fetch pages.
5. A model folder can ship Python. A loader imports it from `config.json` (`auto_map`).
   In `mlx-lm` this ran with no opt-in flag (CVE-2026-5843). rapid-mlx asks for consent first.
   Read that prompt. A `.safetensors` file runs no code; the Python next to it can.

None of these is an attack. The first four are traffic that leaves your computer, from a
process that holds a 5 GB model and reads your prompts. The fifth is code that runs on
your computer. The Makefile starts rapid-mlx with the kill switches set:

```bash
DO_NOT_TRACK=1 RAPID_MLX_TELEMETRY=0 RAPID_MLX_DISABLE_VERSION_CHECK=1 RAPID_MLX_CHAT_WEB_TOOLS=0
```

To check: type `rapid-mlx telemetry status`. The output must show `Reporting: OFF`
and the reason `kill_switch`. An environment variable wins over any saved consent.

After the weights are on your disk, add the offline switches to your shell profile.
Then a model start makes no network request at all:

```bash
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RAPID_MLX_MODEL_MIRROR=""
```

NOTE: These switches are requests. The program agrees to respect them. They are not
enforcement. A firewall that asks before each new outbound connection, such as LuLu,
is what blocks a connection. Block an alert from `python`, `uv` or `rapid-mlx` that
you did not start, and anything that goes to posthog.

NOTE: The model alias `gemma-4-e4b-4bit` does not pin a Hugging Face revision. If a
measurement must be repeatable, record the revision of the weights with the software versions.

### 3.6 Tidbit: a second user is the cheapest sandbox

Every program that you start runs as you. File permissions check who asks, not which
program asks. A file with mode `-rw-------` is private from other users. It is not
private from a model server that runs as you.

A second macOS user changes this with no new software:

| The model runs as | Can it read your files and credentials? | Your Keychain? | GPU speed |
| --- | --- | --- | --- |
| You | Yes, with no prompt | It prompts for unknown programs | Full |
| A Standard user, `ai-playground` | No, after you lock your home folder | No. It has its own | Full |
| A virtual machine | No | No | Much slower |

The procedure has four steps. Do them in this order:

1. Lock your home folder: `chmod go-rwx ~`. Then `ls -ld ~` must start with `drwx------`.
   Every user on a Mac is in the `staff` group, and a home folder lets that group in by default.
2. Make a **Standard** user in System Settings → Users & Groups. Name it `ai-playground`.
   Do not make it an Administrator. Do not sign it in to an Apple Account.
3. Prove the wall: `sudo -u ai-playground ls ~`. The result must be `Permission denied`.
4. Install rapid-mlx inside that user only. Remove it from your own user:
   `uv tool uninstall rapid-mlx`.

Then start the model as `ai-playground` and run the rest of this chapter as yourself:

1. In one terminal, type `make model`. Your own user has no rapid-mlx, so the Makefile
   starts the copy of `ai-playground` through `sudo`. It asks for your password.
2. In a second terminal, type `make server`.
3. In a third terminal, type `make chat`.

`make chat` uses the server on `localhost:9000`. To stop the model, press Ctrl+C in
the first terminal, or type `make model-stop`.
If your second user has a different name, add `MODEL_USER=<name>` to `make model`
and to `make model-stop`.

The second user does not replace the sandbox (3.3).
It closes one gap that the sandbox leaves open: a process that runs as you can read what you can read.

## 4. Select the level of isolation

This chapter gives two levels: the macOS sandbox (3.3) and a second user (3.6).
Stronger levels are available. Select the level from the code that runs:

| Code that runs | Use |
| --- | --- |
| Your code, on your computer | The macOS sandbox (section 3.3), or bubblewrap (`bwrap`) on Linux. Fast. |
| Packages or code that you do not trust | A container with limits on files, CPU, memory, time and network. |
| Hostile code, or many users | A microVM (Firecracker), a sandboxed runtime (gVisor) or a hosted sandbox (E2B, Modal, Daytona). |

Then select the network level:

| Network level | Use |
| --- | --- |
| 1. Offline | `make server-offline`, or a container with `--network none`. Best for analysis of local data. |
| 2. Allowlist | A proxy that permits only the hosts that the task needs. The usual level for an agent. |
| 3. Open | Only for a temporary VM with no secrets in it. |

## 5. Dependencies

`uv.lock` pins each package to one version and one file hash. A pin stops
unexpected changes. A pin does not stop a vulnerability that people find later
in the pinned version.

### 5.1 Scan the dependencies

1. Type `make audit`.
2. Read the result. `uv audit` sends the names and versions in `uv.lock` to the
   OSV database (osv.dev). It does not send your code or your keys.
3. If the scan finds a vulnerability, the command fails.

`make verify` runs `make check` first and then `make audit`. `make check` does
the formatting, lint, type and test steps. It does not use the network.

NOTE: `make audit` needs network access to osv.dev. `make check` does not.

NOTE: `uv audit` is a preview feature of uv. If your uv does not have it, type
`uv self update`.

### 5.2 Fix a vulnerability

1. Find the first fixed version in the result.
2. Update the package: `uv lock --upgrade-package <name>`.
3. If the package is a direct dependency, also change its pin in `pyproject.toml`.
4. Type `make verify`.
5. Commit `uv.lock` and `pyproject.toml` together.

If there is no fixed version, you can accept the risk for some time:

```bash
make audit AUDIT_ARGS="--ignore-until-fixed GHSA-xxxx-xxxx-xxxx"
```

Write the reason in the commit message. When a fix is available, the scan fails again.

### 5.3 Automate the scan

A scan that you must remember to run does not run often. Use automation for two
different jobs: a guard and a helper.

| Job | Tool | What it does | Cost and risk |
| --- | --- | --- | --- |
| Guard | GitHub Actions | `verify.yml` runs `make verify` (with the scan) on each push. `audit.yml` runs `make audit` each Monday. A vulnerability makes the build fail (red). | Free for public repos. It does not change the code. It sends only package names and versions to osv.dev. |
| Guard | Dependabot alerts | GitHub reads `uv.lock` and sends an alert when a new advisory affects a pinned package. | No setup in the repo. Alerts only. |
| Helper | Dependabot pull requests | Opens one pull request for each fix. CI runs the tests on it. | Many small pull requests. You must read each one. |
| Helper | A weekly Claude routine | Upgrades the vulnerable packages, runs `make verify`, and opens one pull request with a short summary in plain words. | Uses model tokens. You must read the pull request before you merge it. |

Use the guard on every repo. Add a helper if you do not want to do the upgrades yourself.

This repo uses the two Actions and Dependabot (`.github/dependabot.yml`). Dependabot
updates `pyproject.toml` and `uv.lock` together. It opens one grouped pull request
each week. It also updates the commit SHAs of the Actions.

Is Dependabot safe? It gets no secrets, it reads only public advisories, and it can
only open pull requests. Two risks remain:

- A bad release. An attacker can publish a poisoned new version, and Dependabot can
  propose it. Two controls apply:
  - A cooldown of 5 days. Dependabot waits 5 days before it proposes a new release.
    Most poisoned versions are found and removed in that time. Security updates do
    not wait.
  - The guard. `verify.yml` runs the tests and the scan on each Dependabot pull
    request. GitHub gives that run a read-only token and no secrets.
- Auto-merge. Do not turn it on. A person reads the pull request and merges it.

To get a pull request as soon as an advisory appears, do this one time:

1. On GitHub, open Settings > Code security.
2. Turn on Dependabot alerts.
3. Turn on Dependabot security updates.

Rules for the automation:

1. Do not give the scan job a secret. It does not need one.
2. Give the job read-only repo permission (`permissions: contents: read`).
3. Pin each third-party Action to a full commit SHA, not to a tag. A tag can move.
4. Do not let a helper merge its own pull request. A person merges.
5. The weekly run is necessary. New advisories appear when the code does not change.

NOTE: This repo works locally. A helper sends its fix as a pull request on GitHub.
Pull that branch, type `make verify`, and merge it.

### 5.4 Tidbit: a lockfile is a snapshot, not a guarantee

A lockfile makes a build repeatable. It also keeps a vulnerable version in place
for a long time. Nothing in the lockfile changes when a new CVE is published.
Run the scan on a schedule, not only when you change the code.

## 6. Checklist: before you give an agent a shell

Start with strict rules. Then make them less strict, one rule at a time.

1. Give the agent write access to one folder only.
2. Block reads of `~/.ssh`, `~/.aws`, `~/.config/gcloud` and the Keychain.
3. Put commands in three groups:
   - Allow: `ls`, `rg`, `pytest`.
   - Ask: `git push`, `pip install`.
   - Deny: `curl | sh`, `rm -rf`, `security`.
4. Give the agent its own key with a short life and a small scope. Do not give it your key.
5. Block outbound traffic. Permit only the hosts that the task needs.
6. Do not obey instructions in content that the agent gets from the web. Treat that content as data.
7. Record each command and its exit code in a log.
8. Use two profiles:
   - Explore: read only, no network.
   - Build: write access to the project, allowlisted network.

NOTE: On macOS, the Desktop, Documents and Downloads folders have TCC protection
(Transparency, Consent and Control: the macOS permission prompts). TCC gives
permission to an app, for example Terminal. Each subprocess gets the
permissions of that app. A sandbox profile that permits writes in one folder only
gives more protection.
