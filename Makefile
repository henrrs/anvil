SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

.PHONY: help inspect test reforge upgrade migrate-runtime doctor capabilities stats databricks-setup rollback

VERSION := $(shell cat VERSION 2>/dev/null || printf 'unknown')

help:
	@printf '%s\n' \
	  'Anvil $(VERSION)' \
	  '' \
	  'make inspect    Inspect the current OpenCode environment. No changes.' \
	  'make test       Run the offline OpenCode 1/2 and Databricks contract suite.' \
	  'make reforge    Rebuild Anvil using the current runtime policy/major.' \
	  'make upgrade    Upgrade Anvil and preserve the installed OpenCode major.' \
	  'make migrate-runtime OPENCODE_MAJOR=2  Explicitly migrate runtime major.' \
	  'make doctor     Check Anvil, runtime, memory, knowledge and project state.' \
	  'make capabilities  Show features available on the detected runtime.' \
	  'make stats      Show native stats, or an honest runtime fallback.' \
	  'make databricks-setup  Configure Databricks; attempts safe CLI install, then SDK fallback.' \
	  '  DRY_RUN=1            Preview providers and auth without changes or network access.' \
	  'make rollback   Restore the latest complete pre-upgrade/rebuild snapshot.' \
	  '' \
	  'upgrade never changes OpenCode major; use migrate-runtime OPENCODE_MAJOR=N for an explicit runtime migration.' \
	  'Set DRY_RUN=1 on upgrade/migrate-runtime to stage and rehearse without changing live files.' \
	  'rollback = restore the prior runtime/configuration snapshot.' \
	  'Set ANVIL_YES=1 only when an automated lifecycle run has been reviewed.'

inspect:
	@bash scripts/inspect.sh

test:
	@bash scripts/test.sh

reforge:
	@bash scripts/reforge.sh

upgrade:
	@bash scripts/upgrade.sh

migrate-runtime:
	@bash scripts/upgrade.sh --migrate-runtime

doctor:
	@bash scripts/doctor.sh

capabilities:
	@python3 scripts/capabilities.py --format "$(if $(FORMAT),$(FORMAT),text)"

stats:
	@bash scripts/stats.sh

databricks-setup:
	@python3 scripts/databricks.py setup $(if $(filter 1 true yes,$(DRY_RUN)),--dry-run,)

rollback:
	@bash scripts/rollback.sh
