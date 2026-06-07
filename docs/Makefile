# Makefile for Hyrum documentation (Canonical Sphinx stack)

DEV_DIR               ?= _dev
SPHINX_OPTS           ?= -c . -d $(DEV_DIR)/.doctrees -j auto
SPHINX_BUILD          ?= $(DOCS_VENVDIR)/bin/sphinx-build
SPHINX_HOST           ?= 127.0.0.1
SPHINX_PORT           ?= 8000
SPHINX_AUTOBUILD_OPTS ?= -D=llms_txt_enabled=0
DOCS_VENVDIR          ?= .venv
DOCS_VENV             ?= $(DOCS_VENVDIR)/bin/activate
DOCS_SOURCEDIR        ?= .
DOCS_BUILDDIR         ?= _build
DOCS_VOCAB            ?= $(DEV_DIR)/styles/config/vocabularies/Canonical
VALE_DIR              ?= $(DOCS_VENVDIR)/lib/python*/site-packages/vale
VALE_CONFIG           ?= $(DEV_DIR)/vale.ini
CHECK_PATH            ?= $(filter-out $(DOCS_VENVDIR) $(DOCS_BUILDDIR),$(wildcard *))

.PHONY: help html epub run serve install spelling spellcheck woke vale \
        vale-install pa11y pa11y-install linkcheck lint-md \
        clean clean-doc full-help

help:
	@echo
	@echo "-------------------------------------------------------------"
	@echo "* watch, build and serve the documentation:  make run"
	@echo "* only build:                                make html"
	@echo "* only serve:                                make serve"
	@echo "* clean built doc files:                     make clean-doc"
	@echo "* clean full environment:                    make clean"
	@echo "* check links:                               make linkcheck"
	@echo "* check spelling:                            make spelling"
	@echo "* check style guide compliance:              make vale"
	@echo "* check inclusive language:                  make woke"
	@echo "-------------------------------------------------------------"
	@echo

# If requirements are updated, venv should be rebuilt and timestamped.
$(DOCS_VENVDIR):
	@echo "... setting up virtualenv"
	python3 -m venv $(DOCS_VENVDIR) || \
	    { echo "You must install python3-venv before you can build the documentation."; exit 1; }
	. $(DOCS_VENV); pip install --require-virtualenv \
	    --upgrade -r requirements.txt \
	    --log $(DOCS_VENVDIR)/pip_install.log
	@test ! -f $(DOCS_VENVDIR)/pip_list.txt || \
	    mv $(DOCS_VENVDIR)/pip_list.txt $(DOCS_VENVDIR)/pip_list.txt.bak
	@. $(DOCS_VENV); pip list --local --format=freeze > $(DOCS_VENVDIR)/pip_list.txt
	@touch $(DOCS_VENVDIR)

install: $(DOCS_VENVDIR)

html: install
	mkdir -p $(DEV_DIR)
	. $(DOCS_VENV); $(SPHINX_BUILD) --fail-on-warning --keep-going -b dirhtml \
	    "$(DOCS_SOURCEDIR)" "$(DOCS_BUILDDIR)" -w $(DEV_DIR)/warnings.txt $(SPHINX_OPTS)

epub: install
	mkdir -p $(DEV_DIR)
	. $(DOCS_VENV); $(SPHINX_BUILD) -b epub \
	    "$(DOCS_SOURCEDIR)" "$(DOCS_BUILDDIR)" -w $(DEV_DIR)/warnings.txt $(SPHINX_OPTS)

run: install
	mkdir -p $(DEV_DIR)
	. $(DOCS_VENV); $(DOCS_VENVDIR)/bin/sphinx-autobuild -b dirhtml \
	    --host $(SPHINX_HOST) --port $(SPHINX_PORT) \
	    "$(DOCS_SOURCEDIR)" "$(DOCS_BUILDDIR)" $(SPHINX_OPTS) $(SPHINX_AUTOBUILD_OPTS)

serve: html
	cd "$(DOCS_BUILDDIR)"; python3 -m http.server --bind $(SPHINX_HOST) $(SPHINX_PORT)

linkcheck: install
	mkdir -p $(DEV_DIR)
	. $(DOCS_VENV); $(SPHINX_BUILD) -b linkcheck -q \
	    "$(DOCS_SOURCEDIR)" "$(DOCS_BUILDDIR)" $(SPHINX_OPTS) || \
	    { grep --color -F "[broken]" "$(DOCS_BUILDDIR)/output.txt"; exit 1; }

vale-install: install
	@. $(DOCS_VENV); test -f $(VALE_CONFIG) || python3 $(DEV_DIR)/get_vale_conf.py
	@echo '.Level=="error" and .Name!="Canonical.500-Repeated-words" and .Name!="Canonical.000-US-spellcheck"' > $(DEV_DIR)/styles/error.filter
	@echo '.Name=="Canonical.000-US-spellcheck"' > $(DEV_DIR)/styles/spelling.filter
	@echo '.Name=="Canonical.400-Enforce-inclusive-terms"' > $(DEV_DIR)/styles/woke.filter

vale: vale-install
	@cat $(DOCS_VOCAB)/accept.txt > $(DOCS_VOCAB)/accept_backup.txt
	@cat $(DOCS_SOURCEDIR)/.custom_wordlist.txt >> $(DOCS_VOCAB)/accept.txt
	@. $(DOCS_VENV); vale --config="$(VALE_CONFIG)" --filter='$(DEV_DIR)/styles/error.filter' \
	    --glob='*.{md,rst}' $(CHECK_PATH)
	@cat $(DOCS_VOCAB)/accept_backup.txt > $(DOCS_VOCAB)/accept.txt && \
	    rm $(DOCS_VOCAB)/accept_backup.txt

spelling: vale-install
	@cat $(DOCS_VOCAB)/accept.txt > $(DOCS_VOCAB)/accept_backup.txt
	@cat $(DOCS_SOURCEDIR)/.custom_wordlist.txt >> $(DOCS_VOCAB)/accept.txt
	@. $(DOCS_VENV); vale --config="$(VALE_CONFIG)" --filter='$(DEV_DIR)/styles/spelling.filter' \
	    --glob='*.{md,rst}' $(CHECK_PATH)
	@cat $(DOCS_VOCAB)/accept_backup.txt > $(DOCS_VOCAB)/accept.txt && \
	    rm $(DOCS_VOCAB)/accept_backup.txt

spellcheck: spelling

woke: vale-install
	@cat $(DOCS_VOCAB)/accept.txt > $(DOCS_VOCAB)/accept_backup.txt
	@cat $(DOCS_SOURCEDIR)/.custom_wordlist.txt >> $(DOCS_VOCAB)/accept.txt
	@. $(DOCS_VENV); vale --config="$(VALE_CONFIG)" --filter='$(DEV_DIR)/styles/woke.filter' \
	    --glob='*.{md,rst}' $(CHECK_PATH)
	@cat $(DOCS_VOCAB)/accept_backup.txt > $(DOCS_VOCAB)/accept.txt && \
	    rm $(DOCS_VOCAB)/accept_backup.txt

pa11y-install:
	@command -v $(PA11Y_CMD) >/dev/null 2>&1 || { \
	    echo "Installing pa11y from npm..."; \
	    mkdir -p $(DEV_DIR)/node_modules/; \
	    npm install --prefix $(DEV_DIR) pa11y; \
	}

pa11y: pa11y-install html
	find $(DOCS_BUILDDIR) -name '*.html' -print0 | xargs -n 1 -0 $(PA11Y_CMD)

clean-doc:
	rm -rf "$(DOCS_BUILDDIR)"
	rm -rf "$(DEV_DIR)/.doctrees"

clean: clean-doc
	@test ! -e "$(DOCS_VENVDIR)" -o -d "$(DOCS_VENVDIR)" -a \
	    "$(abspath $(DOCS_VENVDIR))" != "$(DOCS_VENVDIR)"
	rm -rf "$(DOCS_VENVDIR)"
	rm -rf "$(DEV_DIR)/node_modules"
	rm -rf "$(DEV_DIR)/styles"
	rm -f "$(VALE_CONFIG)"

# Catch-all: route unknown targets to Sphinx's "make mode".
%:
	$(MAKE) --no-print-directory install
	mkdir -p $(DEV_DIR)
	. $(DOCS_VENV); $(SPHINX_BUILD) -M $@ "$(DOCS_SOURCEDIR)" "$(DOCS_BUILDDIR)" $(SPHINX_OPTS) $(O)
