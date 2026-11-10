# Contributing to BrandGuard

Thanks for helping improve BrandGuard. Keep changes focused, explain user-visible behavior, and preserve the project's evidence-first review model.

## Local setup

```bash
git clone https://github.com/aayush-as69/BrandGuard.git
cd BrandGuard
python -m venv .venv
# Activate the virtual environment, then:
pip install -r requirements-dev.txt
python run.py
```

## Before submitting a change

```bash
python -m pytest -q
for f in static/js/*.js; do node --check "$f"; done
```

Run browser tests when Chromium and the Playwright dependencies are installed. See [the testing guide](docs/TESTING.md).

## Contribution guidelines

- Keep all demo fixtures synthetic. Do not commit customer content, credentials, production databases, or confidential brand material.
- Do not weaken server-side access controls, approval requirements, evidence verification, or source redaction to simplify a UI flow.
- Keep AI suggestions optional, labelled, source-grounded, and non-automatic.
- Update the relevant documentation when changing configuration, workflow behavior, data handling, or security boundaries.
- Add or update tests for changed behavior and regressions.
- Prefer small pull requests with a clear summary and test evidence.

## Commit messages

Use short, plain descriptions of the change. Avoid session identifiers, tool names, generated session URLs, or unnecessary trailers.

Examples: `Improve review evidence`, `Update deployment guide`, `Fix approval validation`.
