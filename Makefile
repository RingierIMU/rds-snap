VENV = .venv
PYTHON = $(VENV)/bin/python3
PIP = $(VENV)/bin/pip


# DIRECTORY = $(sort $(dir $(wildcard */)))
# MAIN_DIR = $(shell find . -maxdepth 1 -mindepth 1 -type d -not -iname '.git*')

.PHONY: clean fmt

.DEFAULT_GOAL = help

help:
	@echo "---------------HELP-----------------"
	@echo "To dev the project type make dev"
	@echo "To build the project type make build"
	@echo "To install the project type make install"
	@echo "To format the project type make fmt"
	@echo "To clean the project type make clean"
	@echo "------------------------------------"

clean:
	@find . -maxdepth 3 -mindepth 1 -type d \( -iname '*pycache*' -or -iname 'build' -or -iname 'dist' \) -exec bash -c 'echo "rm -rf {}"' \; | sh
	@rm -rf $(VENV) .vscode rds_snap.egg-info

$(VENV)/bin/activate: requirements_dev.txt requirements.txt
	python3 -m venv $(VENV)
	$(PIP) install pip --upgrade
	$(PIP) install -r requirements_dev.txt -r requirements.txt

build: $(VENV)/bin/activate
	$(PYTHON) setup.py build
	# $(PYTHON) -m build --sdist --wheel --outdir dist/ .

dist: $(VENV)/bin/activate
	$(PYTHON) setup.py sdist bdist_wheel

dev: $(VENV)/bin/activate vscode fmt
	$(PYTHON) setup.py install

install:
	python3 -m pip install -r requirements_dev.txt -r requirements.txt
	python3 setup.py install

.vscode/settings.json: $(VENV)/bin/activate
	@mkdir .vscode
	@echo "{\"python.pythonPath\": \"$(VENV)/bin/python\", \"python.terminal.activateEnvInCurrentTerminal\": true}" > .vscode/settings.json

vscode: .vscode/settings.json

fmt: $(VENV)/bin/activate
	$(PYTHON) -m black .

publish: dist
	$(PYTHON) -m twine upload dist/*