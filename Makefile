# Thin wrapper over dev.py (which also works on Windows without make).
PY ?= python3

.PHONY: setup doctor dev test demo-happy demo-danger demo-uncertain

setup:
	$(PY) dev.py setup

doctor:
	$(PY) dev.py doctor

dev:
	$(PY) dev.py dev

test:
	$(PY) dev.py test

demo-happy:
	$(PY) dev.py demo happy

demo-danger:
	$(PY) dev.py demo danger

demo-uncertain:
	$(PY) dev.py demo uncertain
