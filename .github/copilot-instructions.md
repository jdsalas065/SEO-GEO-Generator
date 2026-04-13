# Copilot Instructions (Backend-only) — SEO-GEO-Generator

You are GitHub Copilot working on this repository.

## Scope & priorities
- This is a Python backend repo. Focus only on Python code unless explicitly asked otherwise.
- Prefer minimal, safe changes; do not refactor unrelated files.
- If requirements are ambiguous, ask targeted questions before coding.
- Never commit secrets (API keys, tokens, credentials) or sample real secrets in docs.
- Keep code production-grade: strong typing where reasonable, clear errors, and deterministic behavior.

## Repository hygiene
- Follow existing project structure and naming conventions.
- Reuse existing helpers/utilities instead of duplicating logic.
- If introducing new modules, keep them small and place them in the most appropriate existing package.

## Code quality rules
- Prefer Python 3.10+ style (type hints, `pathlib`, f-strings).
- Add type hints for new public functions/classes.
- Write docstrings for non-trivial functions.
- Use clear, explicit error messages; avoid silent failures.

## Dependencies
- Do not add new dependencies unless necessary.
- If a new dependency is beneficial, explain why and propose the smallest viable option.

## I/O, files, and CLI behavior
- Be careful with file paths:
  - Prefer `pathlib.Path`
  - Never assume the working directory; resolve paths robustly
- For scripts/CLI entrypoints:
  - Validate inputs early
  - Return non-zero exit codes on failure
  - Print user-friendly messages (but do not leak secrets)

## Configuration & secrets
- Prefer configuration via environment variables and/or existing config files.
- If the project interacts with external services (SEO APIs, LLM APIs, geo services, etc.):
  - never hardcode credentials
  - document required env vars in a safe way (names only)

## Data processing & correctness
- Keep transformations pure and testable when possible.
- If generating outputs (SEO content, geo datasets, reports):
  - ensure deterministic formatting
  - validate required fields
  - handle edge cases (empty input, malformed data, encoding issues)

## Testing expectations
- If the repo already has tests, add/extend them for new behavior.
- If no tests exist, provide:
  - a minimal manual QA checklist
  - example command(s) to run the feature end-to-end

## Output requirements (when you finish a task)
Always provide:
1) Summary of changes
2) Files changed (paths)
3) How to run (exact commands based on the repo’s existing tooling)
4) Manual QA checklist
5) Any notes about backward compatibility and configuration/env vars

## Ask-before-doing list
Ask before:
- adding a new major dependency
- changing public interfaces (CLI args, function signatures used externally)
- changing output formats that users might rely on
- making large-scale refactors or renames