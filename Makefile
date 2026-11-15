SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

.PHONY: help inspect test test-core test-lifecycle reforge upgrade update-runtime doctor capabilities stats databricks-setup rollback eval-engineering eval-engineering-model eval-analytical eval-analytical-semantic eval-analytical-model eval-analytical-full eval-analytical-baseline eval-analytical-review

VERSION := $(shell cat VERSION 2>/dev/null || printf 'unknown')

help:
	@printf '%s\n' \
	  'Anvil $(VERSION)' \
	  '' \
	  'make inspect    Inspect the current OpenCode environment. No changes.' \
	  'make test       Run the offline OpenCode 1 and Databricks contract suite.' \
	  'make reforge    Rebuild Anvil on OpenCode 1; preserves a usable runtime.' \
	  'make upgrade    Upgrade Anvil while preserving the exact OpenCode runtime.' \
	  'make update-runtime  Update OpenCode within supported 1.x releases.' \
	  'make doctor     Check Anvil, OpenCode, memory, knowledge and project state.' \
	  'make capabilities  Show features available on the detected runtime.' \
	  'make stats      Show native stats, or an honest runtime fallback.' \
	  'make databricks-setup  Configure Databricks CLI and validate local readiness.' \
	  'make rollback   Restore the latest complete lifecycle snapshot.' \
	  'make eval-engineering  Replay offline engineering continuity and conformance fixtures.' \
	  'make eval-engineering-model MODE=smoke|challenge|suite  Use local OpenCode config/auth with scoped fixture permissions.' \
	  'make eval-analytical  Run deterministic analytical-intelligence fixtures.' \
	  'make eval-analytical-semantic  Run semantic fixture certification and benchmark.' \
	  '' \
	  'Upgrade is local/offline and preserves the installed OpenCode executable.' \
	  'Set DRY_RUN=1 to preview lifecycle operations without changing live files.' \
	  'Set ANVIL_YES=1 only when an automated lifecycle run has been reviewed.'

inspect:
	@bash scripts/inspect.sh

test:
	@bash scripts/test.sh

test-core:
	@ANVIL_TEST_PHASE=core bash scripts/test.sh

test-lifecycle:
	@ANVIL_TEST_PHASE=lifecycle bash scripts/test.sh

reforge:
	@bash scripts/reforge.sh

upgrade:
	@bash scripts/anvil_upgrade.sh

update-runtime:
	@bash scripts/upgrade.sh --update-runtime

doctor:
	@bash scripts/doctor.sh

capabilities:
	@python3 scripts/capabilities.py --format "$(if $(FORMAT),$(FORMAT),text)" $(if $(filter 1 true yes,$(VERBOSE)),--verbose,)

stats:
	@bash scripts/stats.sh

databricks-setup:
	@python3 scripts/lifecycle_plan.py databricks-setup --format json >/dev/null
	@python3 scripts/databricks.py setup --format "$(if $(OUTPUT),$(OUTPUT),text)" $(if $(filter 1 true yes,$(VERBOSE)),--verbose,) $(if $(filter 1 true yes,$(DRY_RUN)),--dry-run,) $(if $(filter 1 true yes,$(RESET)),--reset,)

eval-engineering:
	@python3 evals/engineering/run.py --fixture "$(if $(FIXTURE),$(FIXTURE),all)" --repeats "$(if $(EVAL_REPS),$(EVAL_REPS),3)" --output "$(if $(REPORT),$(REPORT),/tmp/anvil-engineering-replay.json)"

eval-engineering-model:
	@python3 evals/engineering/local_runner.py --mode "$(if $(MODE),$(MODE),suite)" --fixture "$(if $(FIXTURE),$(FIXTURE),all)" --treatment "$(if $(TREATMENT),$(TREATMENT),anvil-active)" $(if $(OPENCODE),--opencode "$(OPENCODE)",) --model "$(if $(MODEL),$(MODEL),openai/gpt-6-luna)" --variant "$(if $(VARIANT),$(VARIANT),high)" --timeout "$(if $(TIMEOUT),$(TIMEOUT),600)" --evaluation-id "$(if $(EVALUATION_ID),$(EVALUATION_ID),anvil-engineering-local-2026-11-14)" --budget-config "$(if $(BUDGET_CONFIG),$(BUDGET_CONFIG),evals/engineering/live-local-2026-11-14/config.json)" --budget-state "$(if $(BUDGET_STATE),$(BUDGET_STATE),evals/engineering/live-local-2026-11-14/budget-state.json)" --benchmark-manifest "$(if $(BENCHMARK_MANIFEST),$(BENCHMARK_MANIFEST),evals/engineering/live-2026-11-14/benchmarks.json)" --output "$(if $(REPORT),$(REPORT),evals/engineering/live-local-2026-11-14/results.json)"

eval-analytical:
	@python3 -m evals.analytical.cli run --mode deterministic --fixture "$(if $(FIXTURE),$(FIXTURE),all)" $(if $(DATASET),--dataset "$(DATASET)",) $(if $(GROUND_TRUTH),--ground-truth "$(GROUND_TRUTH)",) --benchmark-repetitions "$(if $(EVAL_REPS),$(EVAL_REPS),5)"

eval-analytical-semantic:
	@python3 -m evals.analytical.cli semantic --benchmark-repetitions "$(if $(EVAL_REPS),$(EVAL_REPS),3)"

eval-analytical-model:
	@python3 -m evals.analytical.cli run --mode model --fixture "$(if $(FIXTURE),$(FIXTURE),all)" $(if $(DATASET),--dataset "$(DATASET)",) $(if $(GROUND_TRUTH),--ground-truth "$(GROUND_TRUTH)",) --model "$(MODEL)" --runs "$(if $(RUNS),$(RUNS),1)" --benchmark-repetitions "$(if $(EVAL_REPS),$(EVAL_REPS),5)"

eval-analytical-full:
	@python3 -m evals.analytical.cli run --mode full --fixture "$(if $(FIXTURE),$(FIXTURE),all)" $(if $(DATASET),--dataset "$(DATASET)",) $(if $(GROUND_TRUTH),--ground-truth "$(GROUND_TRUTH)",) --model "$(MODEL)" --runs "$(if $(RUNS),$(RUNS),1)" --benchmark-repetitions "$(if $(EVAL_REPS),$(EVAL_REPS),5)"

eval-analytical-baseline:
	@python3 -m evals.analytical.cli run --mode deterministic --fixture all --freeze-baseline --benchmark-repetitions "$(if $(EVAL_REPS),$(EVAL_REPS),5)"

eval-analytical-review:
	@python3 -m evals.analytical.cli review --report "$(REPORT)" --review "$(REVIEW)" $(if $(GROUND_TRUTH),--ground-truth "$(GROUND_TRUTH)",)

rollback:
	@bash scripts/rollback.sh
