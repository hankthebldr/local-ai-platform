# CLI Output Standard

All CLI output intended for CI/CD consumption uses grepable status tags.

## Tag Format

Tags appear at the start of the line with no leading whitespace.
Each tagged line is self-contained with the format: [TAG] Subject: detail

## Supported Tags

- [OK] - Success
- [ERROR] - Failure, non-zero exit
- [WARN] - Needs attention, does not block
- [INFO] - Informational
- [PASS] - Validation passed
- [FAIL] - Validation failed

## Grep Patterns

    grep '^\[ERROR\]'    # failures
    grep '^\[WARN\]'     # warnings
    grep -c '^\[OK\]'    # success count
    grep '^\[FAIL\]'     # validation failures
    grep '^\[INFO\]'     # informational messages

## Rules

- ASCII characters only
- No Unicode symbols or emojis
- Non-tagged lines may use any formatting
