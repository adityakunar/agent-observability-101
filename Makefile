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
# One switch selects the model: a profile from models.toml. Plain make means the local model.
# Without this default, a personal .env.local selects the model and nothing shows it.
PROFILE     ?= local
export PROFILE
# Make variable names are case-sensitive. A lower-case profile= would be ignored without a
# warning, and the app would use the local model.
ifneq ($(origin profile),undefined)
$(error Write PROFILE=$(profile) in capitals)
endif
MCP_PORT    := 8000
LLM_PORT    := 9000
RUN_DIR     := .run
# Seconds that make up waits. The first start downloads the model weights (about 5 GB).
STARTUP_TIMEOUT ?= 1800
MODEL_URL   := http://localhost:$(LLM_PORT)/v1/models
DESK_URL    := http://localhost:$(MCP_PORT)
PROBE       := curl --connect-timeout 1 --max-time 2 -sf

.DEFAULT_GOAL := help
.PHONY: help up status down check-model model model-stop server chat verify check audit fmt key-status key-set rotate-key scan-secrets chat-offline server-offline

help:
	@echo "Run: one terminal for each command. Ctrl+C stops it."
	@echo "  make model     terminal 1: the local model on :$(LLM_PORT) (Apple silicon Mac)"
	@echo "  make server    terminal 2: the pizza MCP server and the delivery desk on :$(MCP_PORT)"
	@echo "  make chat      terminal 3: the chat; /quit or Ctrl+C to leave"
	@echo "  make server PROFILE=haiku, then make chat PROFILE=haiku"
	@echo "                 use a model profile from models.toml; no make model (SECURITY.md 2.3)"
	@echo "Or start the model and the server in the background"
	@echo "  make up        start both and wait until they answer; then run make chat"
	@echo "  make status    which model the chat will use, and what answers on each port"
	@echo "  make down      stop what make up started"
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

# make model and make server in the background, with logs and process IDs in $(RUN_DIR).
# A part that already answers is left as it is. After a wait that was too short,
# make up again continues the wait: it does not start a second model.
up:
	@mkdir -p $(RUN_DIR)
	@for part in model server; do \
		kill -0 "$$(cat $(RUN_DIR)/$$part.pid 2>/dev/null)" 2>/dev/null || : > $(RUN_DIR)/$$part.pid; \
	done
	@if [ "$(PROFILE)" != local ]; then :; \
	elif [ -s $(RUN_DIR)/model.pid ]; then \
		echo "-> the model from an earlier make up still runs"; \
	elif $(PROBE) $(MODEL_URL) >/dev/null; then \
		echo "-> a model already answers on :$(LLM_PORT). make up uses it and make down will not stop it."; \
	else \
		$(MAKE) --no-print-directory check-model || exit 1; \
		case "$(RAPID_MLX)" in sudo*) sudo -v || exit 1;; esac; \
		echo "-> starting the local model on :$(LLM_PORT)"; \
		nohup $(RAPID_MLX) serve $(LLM_MODEL) --port $(LLM_PORT) $(MLX_ARGS) > $(RUN_DIR)/model.log 2>&1 & \
		echo $$! > $(RUN_DIR)/model.pid; \
	fi
	@if [ -s $(RUN_DIR)/server.pid ]; then \
		echo "-> the pizza server from an earlier make up still runs"; \
	elif $(PROBE) $(DESK_URL)/desk/snapshot >/dev/null; then \
		echo "-> a pizza server already answers on :$(MCP_PORT). It can run older code from another folder:"; \
		echo "   to test this folder, stop that server and run make up again."; \
	else \
		echo "-> starting the pizza server on :$(MCP_PORT)"; \
		nohup $(UV) run --locked python -m agent_observability.pizza.server > $(RUN_DIR)/server.log 2>&1 & \
		echo $$! > $(RUN_DIR)/server.pid; \
	fi
	@echo "-> waiting. The first start downloads the model (about 5 GB). To follow it: tail -f $(RUN_DIR)/model.log"; \
	ready() { { [ "$(PROFILE)" != local ] || $(PROBE) $(MODEL_URL) >/dev/null; } \
		&& $(PROBE) $(DESK_URL)/desk/snapshot >/dev/null; }; \
	for i in $$(seq 1 $(STARTUP_TIMEOUT)); do \
		ready && break; \
		for part in model server; do \
			pid="$$(cat $(RUN_DIR)/$$part.pid 2>/dev/null)"; \
			if [ -n "$$pid" ] && ! kill -0 "$$pid" 2>/dev/null; then \
				echo; echo "ERROR: the $$part stopped while it started. The end of $(RUN_DIR)/$$part.log:" >&2; \
				tail -n 5 $(RUN_DIR)/$$part.log >&2; exit 1; \
			fi; \
		done; \
		printf .; sleep 1; \
	done; echo; \
	ready || { echo "ERROR: not ready after $(STARTUP_TIMEOUT) seconds. What was started still runs: look at $(RUN_DIR)/*.log," >&2; \
		echo "       then run make up again to wait longer, or make down to stop." >&2; exit 1; }
	@$(MAKE) --no-print-directory status

# The first line is the model that make chat will use with this PROFILE.
status:
	@$(UV) run --locked python -c 'from agent_observability.config import describe_model; print(describe_model())'
	@served="$$($(PROBE) $(MODEL_URL) | grep -o '"id": *"[^"]*"' | head -n 1 | cut -d'"' -f4)"; \
		echo "  :$(LLM_PORT)  local model  $${served:-down}"
	@if $(PROBE) $(DESK_URL)/desk/snapshot >/dev/null; then echo "  :$(MCP_PORT)  pizza server UP, delivery desk at $(DESK_URL)"; \
		else echo "  :$(MCP_PORT)  pizza server down"; fi

# Stops only what make up started. A model that another terminal started stays.
# When the model runs as $(MODEL_USER), stopping it asks for your password.
down:
	@started=; [ -s $(RUN_DIR)/model.pid ] && started=yes; \
	for file in $(RUN_DIR)/model.pid $(RUN_DIR)/server.pid; do \
		[ -s "$$file" ] && kill "$$(cat "$$file")" 2>/dev/null; : > "$$file"; \
	done; sleep 1; \
	if ! $(PROBE) $(MODEL_URL) >/dev/null; then echo "stopped."; \
	elif [ -n "$$started" ]; then \
		$(MAKE) --no-print-directory model-stop; \
	else echo "A model that make up did not start still answers on :$(LLM_PORT). To stop it, run: make model-stop"; fi

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
