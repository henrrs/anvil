SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

.PHONY: help inspect test test-core test-lifecycle reforge upgrade update-runtime upgrade-runtime migrate-runtime doctor capabilities stats databricks-setup rollback analytics analytics-dev analytics-status analytics-stop analytics-ui-mock eval-analytics eval-analytical eval-analytical-semantic eval-analytical-model eval-analytical-full eval-analytical-baseline eval-analytical-review

VERSION := $(shell cat VERSION 2>/dev/null || printf 'unknown')

help:
	@printf '%s\n' \
	  'Anvil $(VERSION)' \
	  '' \
	  'make inspect    Inspect the current OpenCode environment. No changes.' \
	  'make test       Run the offline OpenCode 1/2 and Databricks contract suite.' \
	  'make reforge    Rebuild Anvil using the current runtime policy/major.' \
	  'make upgrade    Upgrade Anvil only; preserve the exact validated OpenCode runtime.' \
	  'make update-runtime  Update OpenCode within its current major (network required).' \
	  'make upgrade-runtime  Alias for update-runtime.' \
	  'make migrate-runtime OPENCODE_MAJOR=2  Explicitly migrate OpenCode major.' \
	  'make doctor     Check Anvil, runtime, memory, knowledge and project state.' \
	  'make capabilities  Show features available on the detected runtime.' \
	  'make analytics  Ensure the managed Analytics service is READY and print its URL.' \
	  'make analytics-dev  Run a foreground Analytics development server.' \
	  'make analytics-ui-mock  Preview the UI without Anvil/OpenCode/Databricks (SCENARIO=healthy).' \
	  'make analytics-status  Show Analytics service and URL status.' \
	  'make analytics-stop  Stop the systemd user service when configured.' \
	  'make eval-analytics  Run offline Analytics certification and write report artifacts.' \
	  'make stats      Show native stats, or an honest runtime fallback.' \
	  'make databricks-setup  Configure Databricks; attempts safe CLI install, then SDK fallback.' \
	  'make eval-analytical  Run offline analytical fixtures, scoring and performance evaluation.' \
	  'make eval-analytical-semantic  Run adversarial semantic certification and FAST/STANDARD/DEEP benchmark.' \
	  'make eval-analytical-model MODEL=provider/model RUNS=3  Run blind analysis through installed Anvil.' \
	  'make eval-analytical-full MODEL=provider/model RUNS=3  Run deterministic and blind model evaluation.' \
	  'make eval-analytical-baseline  Freeze the complete 2.14 deterministic baseline once.' \
	  'make eval-analytical-review REPORT=... REVIEW=...  Apply human annotations as a new artifact.' \
	  '  DRY_RUN=1            Preview providers and auth without changes or network access.' \
	  '  RESET=1              Replace only Anvil-owned Databricks config after validation.' \
	  '  OUTPUT=json          Emit structured machine-readable setup results.' \
	  '  VERBOSE=1            Include provider diagnostics in human output.' \
	  'make rollback   Restore the latest complete pre-upgrade/rebuild snapshot.' \
	  '' \
	  'upgrade is local/offline and never resolves or changes an OpenCode release.' \
	  'Use update-runtime for same-major runtime updates and migrate-runtime for explicit major changes.' \
	  'Set DRY_RUN=1 to preview lifecycle operations without changing live files.' \
	  'rollback = restore the prior Anvil or runtime snapshot according to its recorded scope.' \
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

upgrade-runtime: update-runtime

migrate-runtime:
	@bash scripts/upgrade.sh --migrate-runtime

doctor:
	@bash scripts/doctor.sh

capabilities:
	@python3 scripts/capabilities.py --format "$(if $(FORMAT),$(FORMAT),text)" $(if $(filter 1 true yes,$(VERBOSE)),--verbose,)

analytics:
	@python3 scripts/lifecycle_plan.py analytics --format json >/dev/null
	@python3 scripts/analytics_service.py start --port "$(if $(ANALYTICS_PORT),$(ANALYTICS_PORT),$${ANVIL_ANALYTICS_PORT:-8765})"

analytics-dev:
	@python3 scripts/analytics_service.py dev --port "$(if $(ANALYTICS_PORT),$(ANALYTICS_PORT),$${ANVIL_ANALYTICS_PORT:-8765})"

analytics-status:
	@python3 scripts/analytics_service.py status --port "$(if $(ANALYTICS_PORT),$(ANALYTICS_PORT),$${ANVIL_ANALYTICS_PORT:-8765})"

analytics-stop:
	@python3 scripts/analytics_service.py stop --port "$(if $(ANALYTICS_PORT),$(ANALYTICS_PORT),$${ANVIL_ANALYTICS_PORT:-8765})"

analytics-ui-mock:
	@python3 scripts/analytics_ui_mock.py --scenario "$(if $(SCENARIO),$(SCENARIO),healthy)" --port "$(if $(ANALYTICS_PORT),$(ANALYTICS_PORT),8766)"

eval-analytics:
	@python3 -m evals.analytics.certify $(if $(OUTPUT_DIR),--output "$(OUTPUT_DIR)",)

stats:
	@bash scripts/stats.sh

databricks-setup:
	@python3 scripts/lifecycle_plan.py databricks-setup --format json >/dev/null
	@python3 scripts/databricks.py setup --format "$(if $(OUTPUT),$(OUTPUT),text)" $(if $(filter 1 true yes,$(VERBOSE)),--verbose,) $(if $(filter 1 true yes,$(DRY_RUN)),--dry-run,) $(if $(filter 1 true yes,$(RESET)),--reset,)

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
