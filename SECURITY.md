# Security: keys, network and the agent sandbox

This page uses ASD-STE100 Simplified Technical English. The sentences are short.
Each instruction has one action. Procedures use numbered steps.

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
| Agent container | `make agent-container` runs the agent with limits on files, CPU, memory, time and network. |
| Leak scan | `make scan-secrets` scans the files and the git history with gitleaks. |

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

### 2.2 Use a key that is already in the Keychain (same as Lantern)

Lantern keeps one Keychain item for each provider. The service name is the provider
(for example `anthropic` or `nvidia`). The account is your macOS user. This repo can
read the same item. Then one key serves all your projects.

1. If the key is not in the Keychain, type `security add-generic-password -s anthropic -a "$USER" -w`.
2. Paste the key when the prompt shows.
3. In `.env.local`, add these lines:

   ```dotenv
   AGENT_OBSERVABILITY_LLM_BASE_URL=https://api.anthropic.com/v1
   AGENT_OBSERVABILITY_LLM_MODEL=claude-sonnet-5-5
   AGENT_OBSERVABILITY_ALLOWED_HOSTS=api.anthropic.com
   AGENT_OBSERVABILITY_LLM_KEYCHAIN_SERVICE=anthropic
   AGENT_OBSERVABILITY_LLM_API_KEY_EXPIRES=YYYY-MM-DD
   AGENT_OBSERVABILITY_LLM_TEMPERATURE=
   ```

4. Type `make key-status`. Make sure that the output shows `source=keychain:anthropic`.

The empty `LLM_TEMPERATURE` removes the temperature from each request. Newer Claude models
refuse a low temperature. For NVIDIA, use `https://integrate.api.nvidia.com/v1`, the host
`integrate.api.nvidia.com` and the service `nvidia`.

NOTE: A key that Lantern stored has no expiry date in the Keychain. Put the date from the
provider console in `AGENT_OBSERVABILITY_LLM_API_KEY_EXPIRES`. Then the expiry checks work.

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
| `muse` | `meta/muse-glimmer-30b` on NVIDIA NIM | Keychain service `nvidia` |
| `nemotron` | `nvidia/nemotron-3.5-lightning-30b-a3b` on NVIDIA NIM | Keychain service `nvidia` |

To use a profile:

1. Make sure that the key is in the Keychain (section 2.2, step 1).
2. Type `make up PROFILE=haiku`.
3. Type `make chat PROFILE=haiku`.
4. To use the container, type `make agent-container PROFILE=haiku`.

The profile adds its own host to the allowlist for that run only. Other hosts stay blocked.
If you do not set `PROFILE`, the settings in `.env.local` apply.

To add an expiry date or a personal profile, make the file `models.local.toml`. Git ignores it.
Example:

```toml
[haiku]
key_expires = 2027-01-31

[muse]
model = "<model id from build.nvidia.com>"
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
5. Type `make down`. Then type `make up`.
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

Example `.env.local` for a hosted model:

```dotenv
AGENT_OBSERVABILITY_LLM_BASE_URL=https://api.your-provider.example/v1
AGENT_OBSERVABILITY_ALLOWED_HOSTS=api.your-provider.example
```

The check uses exact names. Thus `api.your-provider.example.evil.test` fails. If the
check fails, the app stops before it sends a request.

### 3.2 Inbound traffic to the server

The delivery desk and the MCP tools have no authentication. Thus only your computer must get access to them.

- The server listens on `127.0.0.1:8000`. Other computers cannot connect.
- `make status` shows a warning if a port listens on all interfaces.
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

The agent container (section 4) closes each gap: a proxy with a host allowlist, CPU
and memory caps, a key that stays in the proxy, and a disposable file system.

Use Seatbelt for fast local work with a local model. Use the container when the code,
the packages or the network are not under your control.

## 4. Agent container

### 4.1 What the container gives

`make agent-container` runs one command in a Docker container. The container has these limits:

| Resource | Limit |
| --- | --- |
| Project folder | Mounted at `/work`. Read and write. |
| Data | `DATA` (default `resources/`) mounted at `/data`. Read only. |
| Temporary files | `/tmp` is a `tmpfs` of 1 GB (`TMPFS_SIZE`). Programs cannot run from it. Docker deletes it when the command stops. Tests use `.run/pytest` for temporary files. |
| Root file system | Read only. |
| User | UID 1000. Not root. No Linux capabilities. No new privileges. |
| CPU | 2 CPUs (`AGENT_CPUS`). |
| Memory | 6 GB (`AGENT_MEMORY`). |
| Processes | A maximum of 256. |
| Time | 30 minutes (`AGENT_TIMEOUT`). Then the command stops. |
| Ports | None published. |
| Network | An internal network only. The only exit is the egress proxy. |

### 4.2 Run the container

1. Install Docker Desktop, OrbStack or Colima.
2. Start the model. For a local model, type `make model`.
3. Type `make agent-container`. You get a shell in `/work`.
4. Do your work in the shell. Type `exit` to stop.
5. Read `.run/egress.log` to see all outbound requests.

To run one command, use `CMD`. Examples:

```bash
make agent-container CMD="make verify"
make agent-container CMD="python -m agent_observability.pizza.server" AGENT_TIMEOUT=2h
make agent-container DATA=$HOME/datasets/sales AGENT_MEMORY=8g
```

NOTE: The container installs the Python packages when Docker builds the image. When the command runs, `uv` does not install packages.

### 4.3 The egress proxy

The proxy (`src/agent_observability/egress.py`) is the only exit from the container. It does these things:

1. It permits HTTPS tunnels (`CONNECT` on port 443) only to hosts in
   `security/egress-allowlist.txt`. The default hosts are PyPI and GitHub.
2. It sends requests for `http://proxy:8899/v1/...` to the model API.
3. It adds the `Authorization` header to model requests. It removes any `Authorization` header from the agent.
4. It refuses all other requests with 403. This includes plain HTTP.
5. It writes one JSON line for each request to `.run/egress.log`. The line has the
   host, the status, the bytes and `"new": true` for the first request to a host.

The key goes from the Keychain to the proxy as a Docker secret. The agent container
does not get the key. If the agent is attacked, the attacker cannot read the key.

To permit a new host:

1. Add the host name to `security/egress-allowlist.txt`. Use `.example.com` to permit all subdomains.
2. Run `make agent-container` again.
3. Remove the host when the task is complete.

CAUTION: Each allowlisted host is a possible path for data to leave. Add only the hosts that the task needs.

NOTE: With a local model on Linux, the model must listen on the Docker bridge
address, not on `127.0.0.1`. On macOS, Docker Desktop and OrbStack connect
`host.docker.internal` to the local model.

### 4.4 Select the level of isolation

| Code that runs | Use |
| --- | --- |
| Your code, on your computer | The macOS sandbox (section 3.3), or bubblewrap on Linux. Fast. |
| Packages or code that you do not trust | The agent container (section 4). |
| Hostile code, or many users | A microVM (Firecracker, gVisor) or a hosted sandbox (E2B, Modal, Daytona). |

| Network level | Use |
| --- | --- |
| 1. Offline | `make server-offline`, or `--network none`. Best for analysis of local data. |
| 2. Allowlist | `make agent-container`. The usual level for an agent. |
| 3. Open | Only for a temporary VM with no secrets in it. |

## 5. Checklist: before you give an agent a shell

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

NOTE: On macOS, the Desktop, Documents and Downloads folders have TCC protection.
TCC gives permission to an app, for example Terminal. Each subprocess gets the
permissions of that app. A sandbox profile that permits writes in one folder only
gives more protection.
