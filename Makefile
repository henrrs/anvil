SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

.PHONY: help inspect test test-core test-lifecycle reforge upgrade update-runtime doctor capabilities stats databricks-setup rollback eval-engineering eval-engineering-model

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
	  'make eval-engineering-model MODE=smoke|challenge|suite  Use local OpenCode 1 with fixture-scoped permissions.' \
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
	@python3 evals/engineering/local_runner.py --mode "$(if $(MODE),$(MODE),suite)" --fixture "$(if $(FIXTURE),$(FIXTURE),all)" --treatment "$(if $(TREATMENT),$(TREATMENT),anvil-active)" $(if $(OPENCODE),--opencode "$(OPENCODE)",) --model "$(if $(MODEL),$(MODEL),openai/gpt-6-luna)" --variant "$(if $(VARIANT),$(VARIANT),high)" --timeout "$(if $(TIMEOUT),$(TIMEOUT),600)" $(if $(EVALUATION_ID),--evaluation-id "$(EVALUATION_ID)",) $(if $(BUDGET_CONFIG),--budget-config "$(BUDGET_CONFIG)",) $(if $(BUDGET_STATE),--budget-state "$(BUDGET_STATE)",) $(if $(BENCHMARK_MANIFEST),--benchmark-manifest "$(BENCHMARK_MANIFEST)",) $(if $(REPORT),--output "$(REPORT)",)

rollback:
	@bash scripts/rollback.sh
