# Black Duck SCA snippet license checker

`snippet_check.py` sends your source files to your Black Duck SCA server and reports every snippet match. For each match it gives the license family, license, matched project, release, matched path, and the matching line ranges.

The tool does **not** check matches against your outbound license or your organization's policies. Those decisions remain yours. Snippet matches are evidence to review, not a complete inventory or a legal conclusion. No matches does not prove that no code was reused. For full dependency and license-policy analysis, use a Black Duck Detect scan with license policies.

## Quick start

You need Python 3.9 or later, network access to your Black Duck SCA server, and an API token (see [Create an API token](#create-an-api-token)). The script sends source text only to your Black Duck server. Check your organization's source-sharing rules first.

Windows (PowerShell or Command Prompt), from the extracted folder:

```powershell
.\run.bat samples --dry-run
.\run.bat C:\path\to\your\src
```

macOS or Linux, from the extracted folder:

```sh
./run.sh samples --dry-run
./run.sh /path/to/your/src
```

The first run creates a `.venv` folder and installs `requests`. It needs no administrator access. `--dry-run` lists the files that would be checked and makes no network calls.

On a real run, the script asks for your server URL and API token. The token is not shown while you type. The console then prints match counts by license family and the files to review first. Full reports go to `snippet-output/`. See [Read the results](#read-the-results).

To skip the prompts, set the `BLACKDUCK_URL` and `BLACKDUCK_API_TOKEN` environment variables. CI runs must use these variables, because CI has no terminal to prompt in.

To run without the launchers, install the dependency yourself and call the script:

```sh
python -m pip install -r requirements.txt
python snippet_check.py src
```

## Create an API token

Log in to Black Duck SCA, open the user menu, and select **My Access Tokens**. Select **Create New Token** and choose the scope agreed with your administrator. Copy the token while it is visible and store it securely. See the [Black Duck SCA token instructions](https://docs.blackduck.com/r/blackduck/2026.7/black-duck-documentation/managing-user-access-tokens.html).

The snippet-matching entitlement, role, and token scope the API requires are not documented in the API facts used here. Check with your administrator or Black Duck support. Do not assume that a particular role grants access.

## Read the results

`snippet-output/` contains:

- `summary.md`: match counts by license family, then the files with RECIPROCAL* or UNKNOWN matches first, then skipped and failed files.
- `results.csv`: one row per match with file, license family, license, matched project, release, matched path, source lines, and matched lines. Multiple regions are separated by semicolons. Source lines refer to your file. Matched lines refer to the server's matched file. Cells that start like a formula get an apostrophe prefix for spreadsheet safety.
- `raw/<filename>-<path-hash>.chunk-NNNN.json`: the server response for every completed chunk, including error responses. The path hash keeps same-named files apart. Credentials are redacted if present.

Use a new output folder for each run, for example `--out-dir snippet-output-2`. In a reused folder, old raw files remain, while the CSV and summary are replaced. Raw files contain server-provided paths and metadata and can be sensitive.

If a chunk fails, the reports keep the partial results and the script exits with code 2. Treat exit 2 as an incomplete check, not a clean one.

The table orders families from fewer to more potential obligations. This order is a broad review priority, not a Black Duck risk score or a legal ranking. AGPL and network obligations depend on the actual license and use.

| Family | Review considerations |
| --- | --- |
| PERMISSIVE | Generally fewer reuse conditions. Inspect notice and attribution requirements. |
| WEAK_RECIPROCAL | Limited reciprocal obligations. Inspect the license and how the code is combined. |
| RECIPROCAL | Broader reciprocal obligations can apply. |
| RECIPROCAL_AGPL | Review the reported AGPL license and any network-use obligations. |
| RECIPROCAL_NETWORK | Review the actual license's network-use obligations. |
| UNKNOWN | The family does not show the obligations. Investigate promptly. |

## Reference

### Credentials

The script reads the server URL and token in this order: the `BLACKDUCK_URL` and `BLACKDUCK_API_TOKEN` environment variables, then `--url` and `--token`, then an interactive prompt. The prompt appears only when the script runs in a terminal. Without a terminal, missing values are an error.

Avoid `--token`. Command-line tokens can appear in shell history and process listings. The script never intentionally logs tokens and redacts known credentials from HTTP bodies and errors.

### Options

Run `python snippet_check.py --help` for all options. Example:

```sh
python snippet_check.py src --include '*.java,*.py' --exclude '*generated*' --workers 4 --timeout 90
```

`--include` and `--exclude` take comma-separated globs and can be repeated. Globs match case-sensitive filenames, or absolute paths with forward slashes. The script does not search excluded directories. The default includes cover common source extensions. The default excludes are `.git`, `node_modules`, `.venv`, and `__pycache__`. Files named on the command line also go through these filters. Use `--include '*'` to include all extensions.

The script checks one file at a time by default. `--workers` checks several files at once.

`--dry-run` needs no URL or token and makes no network calls. It lists eligible files with byte sizes, non-whitespace counts, and chunk counts, plus skipped and failed files. It creates no reports. An empty selection is not an error, so review the listing before you use the command in CI.

### Exit codes

| Code | Default behavior | With `--fail-on` |
| --- | --- | --- |
| 0 | No matches | No matches in the listed families. Other matches can exist. |
| 1 | Matches found | At least one match in a listed family |
| 2 | Errors occurred | Errors occurred, even if matches were also found |

CI example, with `BLACKDUCK_URL` and a masked secret `BLACKDUCK_API_TOKEN` set in the CI environment:

```sh
python snippet_check.py src --fail-on RECIPROCAL,RECIPROCAL_AGPL,RECIPROCAL_NETWORK,UNKNOWN
```

### File handling and chunks

The script reads UTF-8 files, including UTF-8 with a BOM. It skips files that contain NUL bytes or other binary control characters, and files that are not valid UTF-8. Convert other encodings to UTF-8 first.

Files with fewer than 300 non-whitespace characters are skipped with a `too small` note. Larger files are split on line boundaries into requests of at most 50,000 non-whitespace characters. A short final chunk overlaps the lines before it, and the script removes identical report rows. Source line numbers map back to the original file.

A single line longer than 50,000 non-whitespace characters is reported as an error. So is a final chunk that cannot reach 300 characters within the limit. The script never sends a chunk outside the limits.

### Response format

The parser was checked against an HTTP 200 response from a real server on October 8, 2026, and against the saved Black Duck REST API 2026.4.0 example. It expects `snippetMatches` grouped by family, with `projectName`, `releaseVersion`, `licenseDefinition`, `matchedFilePath`, and `regions` that hold source and matched start and end arrays. Extra fields are ignored. Missing required fields, malformed regions, or unknown families cause an error instead of a false no-match result.

### Data handling and fingerprints

The script sends raw source text to your configured Black Duck server and to no other service. TLS verification is on by default.

The API also accepts fingerprints in the `application/vnd.blackducksoftware.bill-of-materials-6+json` format, made with a **Black Duck-provided algorithm**. If you cannot send source, ask Black Duck about this option. `fingerprint_payload()` in the script marks where that support would go. Fingerprinting is not implemented, and no algorithm is invented.

## Check a file manually with curl

The body must be raw file text containing **300–50,000 non-whitespace characters**. Curl does not split or check files, so use a UTF-8 file within these limits. First set `BLACKDUCK_URL` and `BLACKDUCK_API_TOKEN` in your shell.

macOS or Linux (zsh or bash). The `python` line needs Python 3 on your `PATH`:

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

## Troubleshooting

- **401:** The script prints the status and body, authenticates again once per chunk, and retries with the new bearer token. If the 401 persists, ask your administrator to check the token and its permissions.
- **TLS or proxy:** Keep verification on. `requests` reads `HTTPS_PROXY`, `HTTP_PROXY`, and `REQUESTS_CA_BUNDLE` for your organization's proxy and CA settings. Check DNS, connectivity, and trust with your administrator. `--insecure` turns verification off and prints a warning. Use it only for a short, deliberate test.
- **Too small or too large:** The limits count non-whitespace characters, not bytes. See [File handling and chunks](#file-handling-and-chunks). Manual curl calls must meet the limits themselves.
- **Other HTTP status:** Only HTTP 200 is documented as success. The script prints other statuses and bodies without guessing their meaning. It retries 429, 5xx, and network errors three times, waiting 1, 2, then 4 seconds. It does not follow redirects. When the retries run out, the script exits with code 2. Send the redacted body and status to support.
- **Parse error:** Compare the raw response with `tests/fixtures/snippet-response.json`. The reports stay partial and the script exits with code 2.
- **The launcher cannot create `.venv`:** Install Python 3.9 or later. On Windows, select **Add python.exe to PATH** in the installer. Then delete any partial `.venv` folder and run again.

## Platform support

The script and tests use only cross-platform Python. Paths with spaces or Unicode work. Quote them in shell commands:

```sh
./run.sh "/Users/yourname/My Project/src" --dry-run
```

The tests cover LF and CRLF line endings, UTF-8 BOM files, Unicode filenames, paths with spaces, directory filtering, and report generation. The test suite and a live API check were run on Windows. No native macOS run has been done yet. On a Mac, run the tests and the sample dry run before you enter your credentials. Then check one known source file and inspect the reports.

## Tests

```sh
python -m unittest discover -s tests -v
```

The tests use a saved live-response fixture and mocked HTTP. They never contact a server.
