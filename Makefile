# Chapter 1: local model + pizza MCP server with its delivery desk, and a terminal chat.
UV          ?= uv
RAPID_MLX_VERSION := 0.16.8
MODEL       ?= gemma-4-e4b-4bit
LLM_MODEL   ?= $(MODEL)
MLX_ARGS    ?=
LLM         ?= auto
MCP_PORT    := 8000
LLM_PORT    := 9000
RUN_DIR     := .run
STARTUP_TIMEOUT ?= 60

.DEFAULT_GOAL := help
.PHONY: help setup check-model model server chat verify check audit fmt up down status logs key-status key-set rotate-key scan-secrets chat-offline server-offline agent-container

help:
	@echo "  make up        start local model + pizza MCP server and delivery desk (background)"
	@echo "  make chat      interactive chat; /quit or Ctrl+C to leave"
	@echo "  make down      stop background services started by this checkout"
	@echo "  make status    show listeners on :$(LLM_PORT) :$(MCP_PORT)"
	@echo "  make logs      tail background logs"
	@echo "  make model | make server   run one service in the foreground"
	@echo "  make verify    make check, then make audit"
	@echo "  make check     formatting, lint, types and offline tests (no network)"
	@echo "  make audit     scan the locked dependencies for known vulnerabilities (OSV, needs network)"
	@echo "  make fmt       format code and fix lint"
	@echo "  make up LLM=external   use a model endpoint you manage yourself"
	@echo "  make key-status        where the API key comes from and when it expires"
	@echo "  make key-set EXPIRES=YYYY-MM-DD     store a key in the macOS Keychain"
	@echo "  make rotate-key EXPIRES=YYYY-MM-DD  replace, verify, then revoke the old key"
	@echo "  make scan-secrets      scan the repo and its history for leaked keys (gitleaks)"
	@echo "  make server-offline | make chat-offline   macOS sandbox: loopback network only"
	@echo "  make agent-container [CMD=...]  run a command in the sandboxed agent container"

setup:
	$(UV) sync --locked

check-model:
	@actual="$$(rapid-mlx --version)" && [ "$$actual" = "rapid-mlx $(RAPID_MLX_VERSION)" ] || { \
		echo "ERROR: Chapter 1 needs rapid-mlx $(RAPID_MLX_VERSION). Run: uv tool install rapid-mlx==$(RAPID_MLX_VERSION)" >&2; exit 1; \
	}

model: check-model
	rapid-mlx serve $(LLM_MODEL) --port $(LLM_PORT) $(MLX_ARGS)

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

# Background services
up: setup
	@mkdir -p $(RUN_DIR)
	@llm_url="$$( $(UV) run --locked python -c 'from agent_observability.config import settings; print(settings.llm_base_url)' )" || exit 1; \
	local_model=0; \
	if [ "$(LLM)" != external ] && [ "$$llm_url" = "http://localhost:$(LLM_PORT)/v1" ]; then \
		local_model=1; \
		if curl --connect-timeout 1 --max-time 2 -sf "$$llm_url/models" >/dev/null 2>&1; then \
			echo "-> using local LLM already listening on :$(LLM_PORT)"; \
		else \
			if [ "$$(uname -s)" != Darwin ] || [ "$$(uname -m)" != arm64 ]; then \
				echo "ERROR: configure an OpenAI-compatible model endpoint and use make up LLM=external." >&2; exit 1; \
			fi; \
			$(MAKE) --no-print-directory check-model || exit 1; \
			echo "-> starting local LLM (:$(LLM_PORT), model $(LLM_MODEL)) ..."; \
			nohup rapid-mlx serve $(LLM_MODEL) --port $(LLM_PORT) $(MLX_ARGS) > $(RUN_DIR)/mlx.log 2>&1 & echo $$! > $(RUN_DIR)/mlx.pid; \
		fi; \
	else echo "-> using configured model endpoint (no model process managed)"; fi; \
	if curl --connect-timeout 1 --max-time 2 -sf http://localhost:$(MCP_PORT)/desk/snapshot >/dev/null 2>&1; then \
		echo "-> using pizza MCP server + delivery desk already listening"; \
	else \
		echo "-> starting pizza MCP server + delivery desk (:$(MCP_PORT)) ..."; \
		nohup $(UV) run --locked python -m agent_observability.pizza.server > $(RUN_DIR)/ui.log 2>&1 & echo $$! > $(RUN_DIR)/ui.pid; \
	fi; \
	printf '%s' "-> waiting for services"; \
	ready=0; for i in $$(seq 1 $(STARTUP_TIMEOUT)); do \
		if { [ "$$local_model" = 0 ] || curl --connect-timeout 1 --max-time 2 -sf "$$llm_url/models" >/dev/null 2>&1; } \
			&& curl --connect-timeout 1 --max-time 2 -sf http://localhost:$(MCP_PORT)/desk/snapshot >/dev/null 2>&1; then ready=1; break; fi; \
		if [ -f $(RUN_DIR)/ui.pid ] && ! kill -0 "$$(cat $(RUN_DIR)/ui.pid)" 2>/dev/null; then break; fi; \
		printf "."; sleep 1; \
	done; echo; \
	if [ "$$ready" != 1 ]; then \
		echo "ERROR: services did not start. Check $(RUN_DIR)/ui.log and $(RUN_DIR)/mlx.log." >&2; \
		exit 1; \
	fi
	@echo "ready -> open the delivery desk at http://localhost:$(MCP_PORT)"
	@echo "         then run make chat and order as the customer; /quit leaves the chat"

# Only stop processes this checkout started; leave a reader's external model alone.
down:
	@pids="$$(cat $(RUN_DIR)/*.pid 2>/dev/null)"; [ -n "$$pids" ] && kill $$pids 2>/dev/null || true
	@rm -f $(RUN_DIR)/*.pid
	@echo "stopped."

status:
	@for p in $(LLM_PORT) $(MCP_PORT); do \
		if lsof -ti TCP:$$p -sTCP:LISTEN >/dev/null 2>&1; then echo "  :$$p  UP"; else echo "  :$$p  down"; fi; \
		if lsof -nP -iTCP:$$p -sTCP:LISTEN 2>/dev/null | grep -Eq '(\*|0\.0\.0\.0|\[::\]):'"$$p"; then \
			echo "  :$$p  WARNING listening on all interfaces; bind it to 127.0.0.1"; fi; \
	done

logs:
	@tail -n +1 -f $(RUN_DIR)/*.log

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
	@[ "$$(uname -s)" = Darwin ] || { echo "sandbox-exec is macOS only; use a container elsewhere." >&2; exit 1; }
	$(SANDBOX) $(UV) run --locked --offline python -m agent_observability.pizza.server

chat-offline:
	@[ "$$(uname -s)" = Darwin ] || { echo "sandbox-exec is macOS only; use a container elsewhere." >&2; exit 1; }
	$(SANDBOX) $(UV) run --locked --offline python -m agent_observability.chat

# Sandboxed agent container: project rw, data ro, capped /tmp, CPU/memory/process caps,
# a wall-clock timeout, no root, read-only root filesystem, and one exit: the egress proxy.
CMD           ?= bash
AGENT_TIMEOUT ?= 30m
COMPOSE       := docker compose -f security/agent-compose.yml

agent-container:
	@command -v docker >/dev/null || { echo "install Docker Desktop, OrbStack or Colima first" >&2; exit 1; }
	@mkdir -p $(RUN_DIR)
	@upstream="$$($(UV) run --locked python -c 'from agent_observability.config import settings; print(settings.llm_base_url)' \
		| sed -E 's#//(localhost|127\.0\.0\.1)([:/])#//host.docker.internal\2#')" || exit 1; \
	key="$$($(UV) run --locked python -c 'from agent_observability.config import llm_api_key; k = llm_api_key(); print("" if k == "not-needed" else k)')" \
		|| { echo "key check failed: see the error above, or run make rotate-key" >&2; exit 1; }; \
	export PROJECT="$(CURDIR)" LLM_UPSTREAM="$$upstream" LLM_API_KEY="$$key"; \
	$(COMPOSE) run --rm --build agent timeout $(AGENT_TIMEOUT) $(CMD); status=$$?; \
	$(COMPOSE) down --remove-orphans >/dev/null 2>&1; \
	echo "egress log: $(RUN_DIR)/egress.log"; exit $$status
