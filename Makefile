# Makefile for Super-Brain

.PHONY: help install install-docs docs serve-docs clean

help:
	@echo "Super-Brain Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  make install      - Install package with all dependencies"
	@echo "  make install-docs - Install with docs dependencies"
	@echo "  make docs         - Build documentation"
	@echo "  make serve-docs   - Serve docs locally"
	@echo "  make clean        - Clean build artifacts"

install:
	pip install -e .

install-docs:
	pip install -e ".[docs]"

docs:
	mkdocs build

serve-docs:
	mkdocs serve

clean:
	rm -rf build/
	rm -rf site/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete