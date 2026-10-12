SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

.PHONY: help inspect test reforge doctor rollback

help:
	@printf '%s\n' \
	  'Anvil 0.1.0' \
	  '' \
	  'make inspect    Inspect the current OpenCode environment. No changes.' \
	  'make test       Validate Anvil in isolated temporary environments.' \
	  'make reforge    Back up, stage, reset and install Anvil with latest stable OpenCode.' \
	  'make doctor     Check the installed Anvil/OpenCode environment.' \
	  'make rollback   Restore the latest valid pre-Anvil backup.' \
	  '' \
	  'For automation, set ANVIL_YES=1 to skip the single reforge confirmation.'

inspect:
	@bash scripts/inspect.sh

test:
	@bash scripts/test.sh

reforge:
	@bash scripts/reforge.sh

doctor:
	@bash scripts/doctor.sh

rollback:
	@bash scripts/rollback.sh
