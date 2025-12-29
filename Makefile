VERSION=$(shell sed -n 's/__version__ = \"\(.*\)\"/\1/p' nx/version.py)

check:
	sed -i "s/^version = \".*\"/version = \"$(VERSION)\"/" pyproject.toml
	uv run ruff check . --select=I --fix
	uv run ruff format .
	uv run ruff check . --fix
	uv run mypy .


build: check
	uv build

release: build
	uv publish
	git tag -a v$(VERSION) -m "Release version $(VERSION)"
	git push --tags
