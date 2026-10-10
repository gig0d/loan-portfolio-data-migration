# Repository instructions

- Work only on the phase authorized by the user. Stop after each phase for review.
- Use synthetic data only; never add real personal or company data.
- Write code, comments, docstrings, documentation, and commit messages in English.
- Keep functions small, add type hints and short public docstrings, and use logging.
- Keep credentials, local configuration, generated data, and reports out of Git.
- Read configuration from the environment; `.env.example` contains safe examples.
- Explain design decisions briefly in `docs/DESIGN.md`.
- Run `python -m pytest` and `python -m ruff check .` after each phase.
- Report check results and suggest a Conventional Commits message. Do not commit
  or start the next phase unless the user asks.
