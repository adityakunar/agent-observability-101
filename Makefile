# Chapter 1: local model + pizza MCP server with its delivery desk, and a terminal chat.
UV          ?= uv
RAPID_MLX_VERSION ?= 1.0.1
# A second macOS user that holds rapid-mlx (SECURITY.md 3.6). Used when this user has no rapid-mlx.
MODEL_USER  ?= ai-playground
LLM_MODEL   ?= gemma-4-e4b-4bit
MLX_ARGS    ?=
# rapid-mlx kill switches: no telemetry, no version check, no web tools in chat (SECURITY.md 3.5).
MLX_ENV     := DO_NOT_TRACK=1 RAPID_MLX_TELEMETRY=0 RAPID_MLX_DISABLE_VERSION_CHECK=1 RAPID_MLX_CHAT_WEB_TOOLS=0
# The rapid-mlx command: this user's copy, or the copy in $(MODEL_USER) through sudo (it asks for your password).
RAPID_MLX   := $(shell if command -v rapid-mlx >/dev/null 2>&1; then echo "env $(MLX_ENV) rapid-mlx"; \
	elif [ -n "$(MODEL_USER)" ] && id "$(MODEL_USER)" >/dev/null 2>&1; then echo "sudo -iu $(MODEL_USER) -- env $(MLX_ENV) rapid-mlx"; fi)
# Make variable names are case-sensitive. A lower-case profile= would be ignored without a
# warning, and the app would use the model from .env.local.
ifneq ($(origin profile),undefined)
$(error Write PROFILE=$(profile) in capitals)
endif
MCP_PORT    := 8000
LLM_PORT    := 9000

.DEFAULT_GOAL := help
.PHONY: help check-model model model-stop server chat verify check audit fmt key-status key-set rotate-key scan-secrets chat-offline server-offline

help:
	@echo "Run: one terminal for each command. Ctrl+C stops it."
	@echo "  make model     terminal 1: the local model on :$(LLM_PORT) (Apple silicon Mac)"
	@echo "  make server    terminal 2: the pizza MCP server and the delivery desk on :$(MCP_PORT)"
	@echo "  make chat      terminal 3: the chat; /quit or Ctrl+C to leave"
	@echo "  make server PROFILE=haiku, then make chat PROFILE=haiku"
	@echo "                 use a model profile from models.toml; no make model (SECURITY.md 2.3)"
	@echo "  make model-stop  stop the model server, also one that $(MODEL_USER) started"
	@echo "Check"
	@echo "  make verify    make check, then make audit"
	@echo "  make check     formatting, lint, types and offline tests (no network)"
	@echo "  make audit     scan the locked dependencies for known vulnerabilities (OSV, needs network)"
	@echo "  make fmt       format code and fix lint"
	@echo "Keys"
	@echo "  make key-status        where the API key comes from and when it expires"
	@echo "  make key-set EXPIRES=YYYY-MM-DD     store a key in the macOS Keychain"
	@echo "  make rotate-key EXPIRES=YYYY-MM-DD  replace, verify, then revoke the old key"
	@echo "  make scan-secrets      scan the repo and its history for leaked keys (gitleaks)"
	@echo "Sandbox"
	@echo "  make server-offline | make chat-offline   macOS sandbox: loopback network only"

check-model:
	@[ -n "$(RAPID_MLX)" ] || { \
		echo "ERROR: rapid-mlx is not installed for $$(id -un), and there is no user $(MODEL_USER)." >&2; \
		echo "       On an Apple silicon Mac, run: uv tool install rapid-mlx==$(RAPID_MLX_VERSION)   (or set it up in a second user: SECURITY.md 3.6)" >&2; \
		echo "       On other computers, rapid-mlx does not run. See the README: Linux or another model endpoint." >&2; exit 1; \
	}
	@actual="$$($(RAPID_MLX) --version 2>/dev/null)"; [ "$$actual" = "rapid-mlx $(RAPID_MLX_VERSION)" ] || { \
		echo "ERROR: this chapter needs rapid-mlx $(RAPID_MLX_VERSION); found '$${actual:-none}'." >&2; \
		echo "       Run: uv tool install rapid-mlx==$(RAPID_MLX_VERSION)   (as $(MODEL_USER) if the model lives there)" >&2; exit 1; \
	}

# Runs in the foreground. When rapid-mlx lives in $(MODEL_USER), sudo asks for your password once.
model: check-model
	$(RAPID_MLX) serve $(LLM_MODEL) --port $(LLM_PORT) $(MLX_ARGS)

model-stop:
	@pkill -f 'rapid-mlx serve' 2>/dev/null \
		|| { [ -n "$(MODEL_USER)" ] && id "$(MODEL_USER)" >/dev/null 2>&1 && sudo -u $(MODEL_USER) pkill -f 'rapid-mlx serve'; } \
		|| true
	@echo "model server stopped."

server:
	$(UV) run --locked python -m agent_observability.pizza.server

chat:
	$(UV) run --locked python -m agent_observability.chat

verify: check audit

check:
	$(UV) run --locked ruff format --check src/ tests/
	$(UV) run --locked ruff check src/ tests/
	$(UV) run --locked mypy src/
	$(UV) run --locked pytest

# Known vulnerabilities in uv.lock (dev tools too), from the OSV database. Needs network,
# so it is not part of check or the offline targets. Accept a finding only with a reason:
# make audit AUDIT_ARGS="--ignore-until-fixed GHSA-xxxx-xxxx-xxxx"
AUDIT_ARGS ?=

audit:
	@$(UV) audit --help >/dev/null 2>&1 || { echo "ERROR: this uv has no audit command. Run: uv self update" >&2; exit 1; }
	$(UV) audit --locked --preview-features audit-command $(AUDIT_ARGS)

fmt:
	$(UV) run --locked ruff format src/ tests/
	$(UV) run --locked ruff check --fix src/ tests/

# Keys: macOS Keychain with an expiry date; see SECURITY.md.
key-status:
	@$(UV) run --locked python -m agent_observability.keys status

key-set:
	@[ -n "$(EXPIRES)" ] || { echo "usage: make key-set EXPIRES=YYYY-MM-DD" >&2; exit 2; }
	@$(UV) run --locked python -m agent_observability.keys set --expires $(EXPIRES)

rotate-key:
	@[ -n "$(EXPIRES)" ] || { echo "usage: make rotate-key EXPIRES=YYYY-MM-DD" >&2; exit 2; }
	@$(UV) run --locked python -m agent_observability.keys rotate --expires $(EXPIRES)

scan-secrets:
	@command -v gitleaks >/dev/null || { echo "install gitleaks first: brew install gitleaks" >&2; exit 1; }
	gitleaks git --redact --no-banner .

# Default-deny egress on macOS: run against a local model with no route off the machine.
SANDBOX = sandbox-exec -f security/loopback-only.sb -D HOME="$$HOME" -D PROJECT="$(CURDIR)" \
	-D UV_CACHE="$$($(UV) cache dir)"

server-offline:
	@[ "$$(uname -s)" = Darwin ] || { echo "sandbox-exec is macOS only." >&2; exit 1; }
	$(SANDBOX) $(UV) run --locked --offline python -m agent_observability.pizza.server

chat-offline:
	@[ "$$(uname -s)" = Darwin ] || { echo "sandbox-exec is macOS only." >&2; exit 1; }
	$(SANDBOX) $(UV) run --locked --offline python -m agent_observability.chat
