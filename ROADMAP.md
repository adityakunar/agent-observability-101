# Chapter roadmap and release handoff

Updated 1 November 2026. **Chapter 1 is complete; Chapter 2 is next.**
Chapters 2–6 below are planned work, not implemented features. Chapters 2–4 follow
the published sequence; assigning the archive to Chapter 5 and human review to
Chapter 6 is a proposal to confirm before writing those chapters.

## Keep the teaching contract

- Serve Python developers and data scientists who want inspectable evidence.
  Each chapter adds one useful layer and needs only the layers beneath it.
- Keep the same Lantern Pizza assistant, Amsterdam tools and operator desk.
  Preserve business behavior while adding ways to examine it.
- Follow the [README journey](README.md): add food, edit quantities/remove an item,
  ask an allergen question, attempt confirmation without an address, select a
  match for `Damrk 1`, review the quote, separately approve, confirm, then cancel.
  Inspect the cart, sources and order before and after each new layer.
- Distinguish what the model **requested**, what the host **executed**, what the
  tool **returned**, what state **changed**, and what the assistant **claimed**.
- The original debugger and six-chapter prototype were deleted. Their lessons
  inform this roadmap; they are not runnable code to copy or validation of this
  repo. Old UK scenarios and address argument shapes do not fit this workflow.

## Chapter 1 — A working assistant and visible business state

**Review question:** Can a reader follow an order and compare the assistant's
words with the real cart, sources and order?

The [article](article.md) and [presentation guide](PRESENTING.md) teach three arcs:
Prefab basics, MCP tools with FAQ observation middleware, and rapid-mlx metrics.
The host owns session identity and execution budgets; tools own business rules.
This baseline has no application tracing, evaluation system or run archive.
Customer approval and accurate answer wording still depend on model behavior.
Offline tests prove host/tool guarantees, not current-model reliability.
[SECURITY.md](SECURITY.md) covers key storage and rotation, model profiles,
network limits, the agent container and the dependency audit.

## Chapter 2 — Record what actually happened

**Review question:** Can a reader explain a failed turn from its recorded
requests, results and state changes, without guessing from tool names?

- Add tracing around [`APIModel.complete`](src/agent_observability/model.py),
  [`Agent.send`](src/agent_observability/client.py) and actual tool execution.
  Preserve the existing loop rather than restoring the old prototype's loop.
- Give records session, turn and call identity, ordered timestamps, effective
  arguments, returned payloads and errors. Retain partial evidence on failure.
  Explain run/trace/span/parent IDs and the record format version explicitly.
- Observe attempts in [`host/steps.py`](src/agent_observability/host/steps.py):
  unavailable tools, budget rejections and suppressed duplicate mutations never
  reach `_dispatch`. Record the decision without inventing an executed call.
- Observe effective session-injected arguments and MCP results in
  [`host/dispatch.py`](src/agent_observability/host/dispatch.py). Its host-only
  `select_delivery_address` calls MCP directly inside dispatch; wrapping only
  `Agent._dispatch` will miss that separate call. Record customer decline too.
- Keep attempted actions separate from successful business events. A rejected
  confirmation creates no order; a quote creates no applied discount. Include
  enough before/after state or state deltas to explain actual changes.
- Link FAQ query arguments, returned text/source references and final answers to
  session and turn. The existing server-wide recent-lookup feed is insufficient
  to attribute evidence to an answer.
- Use one conversation root span; nest discovery, model and tool calls correctly.
  Avoid duplicate counting when MCP client and server both emit tool spans.
  Keep raw message content off exported spans by default; make capture explicit.
- Separate request start, first streamed output, first customer-facing text,
  request completion, tool execution, customer address-selection wait and full
  turn duration. Do not count waiting for the customer as inference latency.
  Keep provider token counts distinct from stream chunks and process-wide memory.
- Derive conversation context/response-time desk metrics from turn records, not
  an extra ad-hoc chat-to-desk POST. Label prompt tokens versus served context
  limit and any median/p90 sample count and scope.
- Release evidence: the README journey still works; a successful run and a
  failure/recovery run are inspectable, including rejection, suppression and
  host-only address selection. Add focused tests for these evidence guarantees.

## Chapter 3 — Check business outcomes

**Review question:** Did the conversation satisfy the business contract, and
which evidence supports each pass or failure?

- Build outcome predicates over Chapter 2 records; accept alternative valid
  tool paths. Test precise ordering/count semantics and both sides of failures.
- Use current Amsterdam events: lookup and customer selection, cart removal,
  quantity change/clear, discount invalidation, confirmation and cancellation.
  A cancelled order retains history but is not an active confirmation.
- Seed known faults across `prompt`, `tool`, `faq_source` and `domain_rule` before
  presenting fault attribution as useful. Include assistant claims as evidence
  to examine; a confirmation claim does not prove an order exists.
- Treat loop/budget exhaustion as stored failure data. Keep ambiguous approval
  intent for a semantic criterion; evaluation does not enforce authorization.

## Chapter 4 — Judge language against evidence

**Review question:** Does the answer preserve the facts, and can we trust the
grader's verdict on cases where the truth is known?

- Give the judge per-turn conversation, normalized tool results and retrieved
  context. Separate retrieval success, business success and answer faithfulness.
- Calibrate on committed known-pass/known-fail transcripts: invented menu items,
  fabricated confirmation, missing context and legitimate short approval.
  Scope rubrics to verifiable facts; inspect disagreement with Chapter 3 checks.
- Before hosted grading, scrub at the record/export boundary, disclose exactly
  what leaves the machine and fail closed if the required scrubber is unavailable.
  Measure false positives/misses; distinguish local storage from outbound privacy.
- Keep hosted grading optional, identify its provider/model and report failures.
  A judge score is evidence to review, not ground truth or production reliability.

## Proposed Chapter 5 — Save runs and learn across them

**Review question:** Can we recover, compare and reuse the evidence from a run?

- Save self-contained, versioned session records in `finally`, including partial
  runs, interrupts and judge failures. Include spans, verdicts, human/simulated
  origin and provenance: code/prompt/model, weight revision when known, serving
  version, sampling/context configuration and hardware where relevant.
- Make privacy status visible; support inspecting, deleting and exporting records.
  Start with terminal history before introducing another viewer or trace store.
- Export human-labeled runs into judge-calibration fixtures. Keep old vocabulary
  intact; historical model/configuration changes do not form a current benchmark.

## Proposed Chapter 6 — Review disagreements with a human

**Review question:** Can a reviewer explain a disputed verdict and turn that
judgment into a reusable calibration example?

- Extend the existing Prefab desk with evidence beside checkpoint/judge verdicts.
  Prioritize disagreements; the new view must help explain or label a real case.
- Store human verdicts on the same check IDs with `layer: human`; preserve their
  provenance and export them through the Chapter 5 record contract.
- Keep aggregate review signals advisory. Before flagging constant checkpoints,
  require at least 20 diverse runs; agreement analysis needs at least 20 pairs
  including five pass and five fail cases. Simulated customers discover cases;
  they do not establish an unbiased reliability estimate.

## Release checklist for every chapter

- Answer that chapter's review question against inspectable evidence; keep one
  coherent teaching increment rather than collecting unrelated features.
- Preserve the README journey and business guarantees. Run full `make verify`
  from a clean locked environment; review every intended dependency/lock change.
- Rehearse with the current model and browser; record software/model provenance
  and what was actually exercised. A successful walkthrough is not a benchmark.
  Keep unverified Linux/Ollama or hosted recipes explicitly labeled.
- Check cited sources and claims, screenshots and relative links. Update the
  article, README, presentation guide and this roadmap together.
- Keep one branch, `main`, with one commit per chapter. Work on a chapter in a
  short-lived branch or pull request, then squash it into a single
  `Chapter N: …` commit on `main`. Tag that commit `chapter-N` and publish a
  release. Never move or delete an earlier chapter tag, so readers can reproduce it.
- Dependabot pull requests are part of the next chapter: merge them into its
  working branch, or squash them into its commit, not onto `main` alone.

## Experiments that must earn a later chapter

Model comparisons, selective tool/skill discovery, multi-agent roles, web search,
an online PDOK address adapter and judge alignment are deferred. First identify
an observed problem and comparison evidence. Measure business success, errors,
context and latency before adding orchestration, loading mechanisms or services.
