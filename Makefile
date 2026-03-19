.PHONY: install install-hooks test clean help

help:
	@echo "GitNexus Stable Ops - Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  make install              Install gni wrapper to ~/.local/bin"
	@echo "  make install-hooks REPO=  Install git hooks to a repository"
	@echo "  make test                 Run unit tests"
	@echo "  make clean                Remove temporary files"
	@echo "  make help                 Show this help message"

install:
	@echo "Installing gni wrapper..."
	@mkdir -p $(HOME)/.local/bin
	@ln -sf $(PWD)/bin/gni $(HOME)/.local/bin/gni
	@chmod +x bin/*
	@chmod +x lib/parse_graph_meta.py
	@echo "✓ Installed gni to $(HOME)/.local/bin/gni"
	@echo "  Ensure $(HOME)/.local/bin is in your PATH"

install-hooks:
ifndef REPO
	$(error REPO is required. Usage: make install-hooks REPO=/path/to/repo)
endif
	@bin/gitnexus-install-hooks.sh "$(REPO)"

test:
	@echo "Running tests..."
	@bash tests/test_common.sh
	@bash tests/test_hooks.sh

clean:
	@echo "Cleaning temporary files..."
	@rm -f /tmp/gitnexus-*.log
	@rm -f /tmp/graph-meta-update.log
	@echo "✓ Cleaned"
