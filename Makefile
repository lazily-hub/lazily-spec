.RECIPEPREFIX := >

LAKE ?= lake
LEAN_DIR ?= formal/lean

.PHONY: \
	check \
	test-lean-formal

check: test-lean-formal

test-lean-formal:
>cd "$(LEAN_DIR)" && $(LAKE) build
