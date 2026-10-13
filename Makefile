SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

.PHONY: help inspect test reforge upgrade doctor stats rollback

VERSION := $(shell cat VERSION 2>/dev/null || printf 'unknown')

help:
	@printf '%s\n' \
	  'Anvil $(VERSION)' \
	  '' \
	  'make inspect    Inspect the current OpenCode environment. No changes.' \
	  'make test       Validate V2 in isolated temporary environments.' \
	  'make reforge    Clean installation or full rebuild from the Anvil baseline.' \
	  'make upgrade    Rehearse and migrate the existing Anvil installation forward.' \
	  'make doctor     Check Anvil, OpenCode, memory, knowledge and project state.' \
	  'make stats      Show OpenCode native usage statistics.' \
	  'make rollback   Restore the latest complete pre-upgrade/rebuild snapshot.' \
	  '' \
	  'reforge = clean installation/rebuild; upgrade = forward migration; rollback = restore the prior runtime/configuration snapshot.' \
	  'Set ANVIL_YES=1 only when an automated lifecycle run has been reviewed.'

inspect:
	@bash scripts/inspect.sh

test:
	@bash scripts/test.sh

reforge:
	@bash scripts/reforge.sh

upgrade:
	@bash scripts/upgrade.sh

doctor:
	@bash scripts/doctor.sh

stats:
	@bash scripts/stats.sh

rollback:
	@bash scripts/rollback.sh
