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
.PHONY: help setup check-model model server chat verify fmt up down status logs

help:
	@echo "  make up        start local model + pizza MCP server and delivery desk (background)"
	@echo "  make chat      interactive chat; /quit or Ctrl+C to leave"
	@echo "  make down      stop background services started by this checkout"
	@echo "  make status    show listeners on :$(LLM_PORT) :$(MCP_PORT)"
	@echo "  make logs      tail background logs"
	@echo "  make model | make server   run one service in the foreground"
	@echo "  make verify    formatting, lint, types and offline tests"
	@echo "  make fmt       format code and fix lint"
	@echo "  make up LLM=external   use a model endpoint you manage yourself"

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

verify:
	$(UV) run --locked ruff format --check src/ tests/
	$(UV) run --locked ruff check src/ tests/
	$(UV) run --locked mypy src/
	$(UV) run --locked pytest

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
	done

logs:
	@tail -n +1 -f $(RUN_DIR)/*.log
