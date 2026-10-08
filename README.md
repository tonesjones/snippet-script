# Black Duck SCA snippet license checker

Check source files for snippet matches and report the license family, license, project, release, matched path, and source/matched line regions. The Python script uses only `requests` and the standard library, and uses portable Python APIs for Windows, macOS, and Linux with Python 3.9 or later.

This tool does **not** evaluate conflicts against your outbound license or your organization's policies. Those decisions remain yours. For broader dependency and license-policy analysis, use a full Black Duck Detect scan with license policies. Snippet matches are evidence to review, not a complete inventory or a legal conclusion. Chunk boundaries can affect matching; no matches does not prove absence of reused code.

## Prerequisites

- Your Black Duck SCA server URL and network access to it.
- An API token belonging to a user permitted to call the API.
- Python 3.9+ and `requests`: `python -m pip install requests`.

The required snippet-matching entitlement, role, and token scope are not documented in the API facts used here. Check with your administrator or Black Duck support; do not assume any particular role grants access.

## Create an API token

Log in, open the user menu, select **My Access Tokens**, then **Create New Token**. Choose the scope agreed with your administrator, create the token, and copy it while it is visible. Store it securely. See the [Black Duck SCA token instructions](https://docs.blackduck.com/r/blackduck/2026.7/black-duck-documentation/managing-user-access-tokens.html).

## Quick start

Prefer environment variables; they take precedence over `--url` and `--token`. Avoid command-line tokens, which can appear in shell history or process listings. The script never intentionally logs tokens and redacts known credentials from HTTP bodies and errors.

macOS Terminal (zsh or bash), or Linux: create a virtual environment in the extracted package folder first. Install Python 3.9+ if `python3` is unavailable or older than 3.9.

```sh
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install requests
python -m unittest discover -s tests -v
python snippet_check.py samples --dry-run
```

After activation, `python` refers to this environment. These commands require no administrator access. Enter your token at the hidden prompt:

```sh
export BLACKDUCK_URL='https://your-blackduck-server'
BLACKDUCK_API_TOKEN=$(python -c 'import getpass; print(getpass.getpass("API token: "))')
export BLACKDUCK_API_TOKEN
python snippet_check.py src/example.c
python snippet_check.py src --out-dir snippet-output
python snippet_check.py src --dry-run
```

Windows PowerShell:

```powershell
$env:BLACKDUCK_URL = 'https://your-blackduck-server'
$secret = Read-Host 'API token' -AsSecureString
$env:BLACKDUCK_API_TOKEN = [System.Net.NetworkCredential]::new('', $secret).Password
python snippet_check.py src/example.c
python snippet_check.py src --out-dir snippet-output
python snippet_check.py src --dry-run
```

CI example: configure `BLACKDUCK_URL` and a masked secret `BLACKDUCK_API_TOKEN` in your CI environment, then run:

```sh
python snippet_check.py src --fail-on RECIPROCAL,RECIPROCAL_AGPL,RECIPROCAL_NETWORK,UNKNOWN
```

Exit codes:

| Code | Default behavior | With `--fail-on` |
| --- | --- | --- |
| 0 | No matches | No matches in the listed families; other matches may exist |
| 1 | Matches found | At least one match in a listed family |
| 2 | Errors occurred | Errors occurred, even if matches were also found |

Use `python snippet_check.py --help` for all options. Examples:

```sh
python snippet_check.py src --include '*.java,*.py' --exclude '*generated*' --workers 4 --timeout 90
```

Include/exclude options accept comma-separated globs and can be repeated. Globs match case-sensitive filenames or absolute paths with forward slashes; matching directories are pruned for exclusions. Default includes cover common source extensions; default exclusions skip `.git`, `node_modules`, `.venv`, and `__pycache__`. Explicit files also respect include/exclude filters. Use `--include '*'` to include other extensions. Processing is sequential by default; `--workers` enables concurrent files.

UTF-8 (including UTF-8 BOM) is supported. NUL bytes, other binary control characters, and non-UTF-8 files are skipped. Convert other text encodings to UTF-8 first. Files below 300 non-whitespace characters are skipped with a `too small` note. Large files are split on line boundaries into requests of at most 50,000 non-whitespace characters. A final short chunk overlaps preceding lines; identical report rows are deduplicated. Source lines are mapped to original file positions. A line that itself exceeds 50,000 characters, or a tail that cannot be extended within the limit, is reported as an error. No invalid-size chunk is sent.

Dry-run needs no URL or token and makes no network calls. It lists eligible files with byte sizes, non-whitespace counts, and chunk counts, plus skipped/failed notes. It creates no reports. An empty selection is not an error: review the listing before CI use.

## Manual method: curl

The body must be raw file text containing **300–50,000 non-whitespace characters**. Curl does not split or validate files; use a valid-size UTF-8 file. Set the environment variables as above.

macOS Terminal (zsh or bash), or Linux (activate the Python environment above first):

```sh
curl --silent --show-error --request POST \
  "$BLACKDUCK_URL/api/tokens/authenticate" \
  --header "Authorization: token $BLACKDUCK_API_TOKEN" \
  --header 'Accept: application/vnd.blackducksoftware.user-4+json' \
  --output auth.json --write-out 'HTTP %{http_code}\n'
# Continue only if the printed status is 200; otherwise inspect auth.json.
BEARER=$(python -c 'import json; print(json.load(open("auth.json"))["bearerToken"])')
curl --silent --show-error --request POST \
  "$BLACKDUCK_URL/api/snippet-matching" \
  --header "Authorization: Bearer $BEARER" \
  --header 'Content-Type: text/plain' \
  --header 'Accept: application/vnd.blackducksoftware.bill-of-materials-6+json' \
  --data-binary @src/example.c \
  --output matches.json --write-out 'HTTP %{http_code}\n'
# Continue only for HTTP 200; inspect matches.json for any other status.
rm -f auth.json
unset BEARER BLACKDUCK_API_TOKEN
```

Windows PowerShell equivalents use `curl.exe` to avoid the Windows PowerShell `curl` alias:

```powershell
$status = curl.exe --silent --show-error --request POST `
  "$env:BLACKDUCK_URL/api/tokens/authenticate" `
  --header "Authorization: token $env:BLACKDUCK_API_TOKEN" `
  --header 'Accept: application/vnd.blackducksoftware.user-4+json' `
  --output auth.json --write-out '%{http_code}'
if ($LASTEXITCODE -ne 0 -or $status -ne '200') {
  Get-Content auth.json
  throw "Authentication failed: HTTP $status"
}
$bearer = (Get-Content auth.json -Raw | ConvertFrom-Json).bearerToken
$status = curl.exe --silent --show-error --request POST `
  "$env:BLACKDUCK_URL/api/snippet-matching" `
  --header "Authorization: Bearer $bearer" `
  --header 'Content-Type: text/plain' `
  --header 'Accept: application/vnd.blackducksoftware.bill-of-materials-6+json' `
  --data-binary '@src/example.c' `
  --output matches.json --write-out '%{http_code}'
Write-Host "HTTP $status"
if ($LASTEXITCODE -ne 0 -or $status -ne '200') { Get-Content matches.json }
Remove-Item -LiteralPath auth.json
$bearer = $null
Remove-Item Env:BLACKDUCK_API_TOKEN
```

`auth.json` contains a credential: protect and delete it after use. Manual curl headers can expose credentials in process listings; use the script for routine automation. Do not share authentication responses.

## Reading results

`--out-dir` contains:

- `raw/<filename>-<path-hash>.chunk-NNNN.json`: response body for every completed chunk, including error bodies. Non-JSON bodies retain this filename. Credentials are redacted if present. Names use a path hash to distinguish same-named files. Reports use absolute original file paths; chunk numbering follows source order.
- `results.csv`: file, license family, license, matched project, release, matched path, source lines, matched lines. Multiple regions are separated by semicolons. Source lines refer to the original file; matched lines refer to the server's matched file. Formula-like cells are prefixed with an apostrophe for spreadsheet safety.
- `summary.md`: match-record counts by family; files with RECIPROCAL* or UNKNOWN matches first; skipped and failed files. Partial results remain available when a chunk fails. Exit 2 means the overall result is incomplete.

Use a fresh output directory for each run: old raw files in a reused directory are retained, while CSV and summary are replaced. Raw files contain server-provided paths and metadata and may be sensitive.

The table below orders families by a broad review priority from lower to higher potential obligations. This is not a Black Duck risk score or a universally applicable legal ranking; AGPL/network obligations depend on the actual license and use. UNKNOWN has uncertain obligations, so review it promptly.

| Family | Review considerations |
| --- | --- |
| PERMISSIVE | Generally fewer reuse conditions; inspect notice and attribution requirements. |
| WEAK_RECIPROCAL | Limited reciprocal obligations; inspect the license and how code is combined. |
| RECIPROCAL | Broader reciprocal obligations may apply. |
| RECIPROCAL_AGPL | Review the reported AGPL license and applicable network-use obligations. |
| RECIPROCAL_NETWORK | Review the actual license's network-use obligations. |
| UNKNOWN | License obligations cannot be determined from this family; investigate. |

The parser was verified against an HTTP 200 response from a real server on October 8, 2026, and the saved Black Duck REST API 2026.4.0 example. It expects `snippetMatches` grouped by family with `projectName`, `releaseVersion`, `licenseDefinition`, `matchedFilePath`, and `regions` containing source/matched start/end arrays. Extra fields are ignored. Missing required fields, malformed regions, or unfamiliar families produce an error rather than a false no-match result; inspect the raw JSON.

## Data handling and fingerprints

Raw source text is sent to your configured Black Duck server. Check your organization's source-sharing rules before running the tool. It does not upload to any other service. TLS verification is enabled by default.

The API also accepts fingerprints using `application/vnd.blackducksoftware.bill-of-materials-6+json`, generated with a **Black Duck-provided algorithm**. Customers unable to send source should ask Black Duck about this option. The script's `fingerprint_payload()` is a clearly marked extension point; fingerprinting is not implemented and no algorithm is invented.

## Troubleshooting

- **401:** The script prints the status/body and re-authenticates once per chunk, then retries with the new bearer. If it persists, ask your administrator to check the token and permissions. The endpoint's undocumented error semantics are not assumed.
- **TLS or proxy:** Keep verification enabled. `requests` supports `HTTPS_PROXY`/`HTTP_PROXY` and `REQUESTS_CA_BUNDLE` for your organization's proxy/CA configuration. Check DNS, connectivity, and trust with your administrator. `--insecure` disables verification and prints a warning; use it only for a deliberate temporary diagnostic.
- **Too small/large:** The limits count non-whitespace characters, not bytes. Short files are skipped. Large files are chunked as described above; very long individual lines can fail. Manual curl calls must meet the limits themselves.
- **Non-200:** Only HTTP 200 is documented as success. The script prints other statuses and response bodies without guessing their meaning. It retries 429 and 5xx as an operational strategy, with three retries and 1/2/4-second backoff; network exceptions use the same strategy. Redirects are not followed. Exhausted retries result in exit 2. Contact support with the redacted body and status.
- **Parsing error:** Inspect the raw response and compare its shape with the fixture. Reports stay partial and exit 2; do not treat that as a clean check.

## Platform verification

The script and tests use cross-platform Python APIs; there are no Windows-only runtime dependencies. Paths containing spaces or Unicode are supported; quote paths in shell commands, for example:

```sh
python snippet_check.py "/Users/yourname/My Project/src" --dry-run
```

Tests cover LF (macOS/Linux) and CRLF (Windows) line endings, UTF-8 BOM files, Unicode filenames, paths with spaces, directory filtering, and report generation. The automated suite and live API check were run on Windows. A native macOS run has not yet been performed. On a Mac, run the setup, tests, and sample dry-run above before using your server credentials; then run one known source file and inspect the generated reports.

## Tests

```sh
python -m unittest discover -s tests -v
```

Tests use a saved live-response fixture and mocked HTTP only; they never contact a server. They cover counting, chunk limits/overlap, source line mapping, defensive parsing, retry/re-authentication, report generation, exit codes, and dry-run behavior.
