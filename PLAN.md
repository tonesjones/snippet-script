# Plan: easier end-user experience

Branch: `usability-improvements` → PR into `main`.

## 1. Prompt for missing credentials
When `BLACKDUCK_URL` / `BLACKDUCK_API_TOKEN` (and `--url`/`--token`) are missing and stdin is a TTY,
prompt for the URL with `input()` and the token with `getpass.getpass()`. Non-TTY keeps the current error.
- Acceptance: interactive run with no env vars prompts; token is not echoed; non-TTY still exits with
  the existing error; new unit tests cover both paths (mocked `isatty`, `input`, `getpass`).

## 2. `requirements.txt`
- Acceptance: file pins `requests` with a minimum version; README install step uses `pip install -r requirements.txt`.

## 3. One-step launchers
`run.ps1`, `run.bat` (calls run.ps1 or does the same), `run.sh`: create `.venv` if missing, install
requirements, run `snippet_check.py` forwarding all arguments and exit code.
- Acceptance: `run.bat samples --dry-run` works from a clean checkout on Windows; `run.sh` is POSIX sh,
  executable bit set via `.gitattributes`/git; exit code is passed through.

## 4. Console summary
After a real (non-dry) run, print counts per license family and up to 10 files with RECIPROCAL*/UNKNOWN matches.
- Acceptance: unit test checks the printed summary; existing tests still pass.

## 5. README restructure
Short Quick start at top (launcher → run → read results); reference material below. Use technical-writing skill.
- Acceptance: Quick start ≤ ~10 lines per OS; no content lost; matches new behaviour.

## Status
- [x] 1-5 done on 2026-10-08. 19 tests pass; `run.bat samples --dry-run` checked on Windows.
- Manual curl section split into numbered copy-paste steps per OS; tested against a mock server
  in Git Bash, PowerShell 7, and Windows PowerShell 5.1.
- Next: run `run.sh` on a real Mac. Nice later: timestamped output folders, `pyproject.toml`
  entry point, quieter test output, an optional HTML report.
- Open decisions: none.
