"""Check UTF-8 source files against Black Duck SCA snippet matching (Python 3.9+)."""
import argparse
import csv
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import requests

FAMILIES = ('PERMISSIVE', 'WEAK_RECIPROCAL', 'RECIPROCAL', 'RECIPROCAL_AGPL',
            'RECIPROCAL_NETWORK', 'UNKNOWN')
DEFAULT_INCLUDE = '*.c,*.h,*.cpp,*.hpp,*.cc,*.cxx,*.java,*.py,*.js,*.jsx,*.ts,*.tsx,*.cs,*.go,*.rs,*.rb,*.php,*.swift,*.kt,*.m,*.mm,*.sh,*.scala'
FIELDS = ['file', 'license family', 'license', 'matched project', 'release',
          'matched path', 'source lines', 'matched lines']
MIN_CHARS, MAX_CHARS = 300, 50000
ACCEPT = 'application/vnd.blackducksoftware.bill-of-materials-6+json'


def non_whitespace(text):
    return sum(not c.isspace() for c in text)


def chunk_text(text):
    """Return (text, zero-based original line offset); overlap a short tail."""
    lines = text.splitlines(keepends=True)
    counts = [non_whitespace(line) for line in lines]
    if any(n > MAX_CHARS for n in counts):
        raise ValueError('single line exceeds 50,000 non-whitespace characters')
    chunks = []
    start = 0
    while start < len(lines):
        end, size = start, 0
        while end < len(lines) and size + counts[end] <= MAX_CHARS:
            size += counts[end]
            end += 1
        if size < MIN_CHARS:
            while start > 0 and size < MIN_CHARS:
                start -= 1
                size += counts[start]
            if size < MIN_CHARS or size > MAX_CHARS:
                raise ValueError('cannot form a valid final chunk on line boundaries')
        chunks.append((''.join(lines[start:end]), start))
        start = end
    return chunks


def line_ranges(regions, prefix, offset):
    starts, ends = regions.get(prefix + 'StartLines'), regions.get(prefix + 'EndLines')
    if not isinstance(starts, list) or not isinstance(ends, list) or len(starts) != len(ends):
        raise ValueError('missing or inconsistent line-region arrays')
    result = []
    for a, b in zip(starts, ends):
        if type(a) is not int or type(b) is not int or a < 1 or b < a:
            raise ValueError('invalid line region')
        result.append(f'{a + offset}-{b + offset}')
    if not result:
        raise ValueError('empty line-region arrays')
    return '; '.join(result)


def parse_response(payload, file, offset=0):
    """Parse the observed snippetMatches schema; reject unknown shapes."""
    if not isinstance(payload, dict) or not isinstance(payload.get('snippetMatches'), dict):
        raise ValueError('expected snippetMatches object; inspect raw JSON')
    rows = []
    for family, matches in payload['snippetMatches'].items():
        if family not in FAMILIES or not isinstance(matches, list):
            raise ValueError('unrecognized license family or match list; inspect raw JSON')
        for match in matches:
            if not isinstance(match, dict):
                raise ValueError('expected match object')
            license_def, regions = match.get('licenseDefinition'), match.get('regions')
            if not isinstance(license_def, dict) or not isinstance(regions, dict):
                raise ValueError('missing licenseDefinition or regions')
            license_name = (license_def.get('licenseDisplayName') or
                            license_def.get('name') or license_def.get('spdxId'))
            values = [license_name, match.get('projectName'), match.get('releaseVersion'),
                      match.get('matchedFilePath')]
            if any(not isinstance(v, str) or not v for v in values):
                raise ValueError('missing license, project, release, or matched path')
            rows.append(dict(zip(FIELDS, [str(file), family] + values +
                                 [line_ranges(regions, 'source', offset),
                                  line_ranges(regions, 'matched', 0)])))
    return rows


def fingerprint_payload(text):
    """Extension point: use ONLY a Black Duck-provided fingerprint algorithm.

    A future implementation must also change Content-Type to ACCEPT above.
    No fingerprint algorithm is implemented or inferred here.
    """
    raise NotImplementedError('Black Duck-provided fingerprint algorithm required')


class Client:
    def __init__(self, url, token, timeout=60, verify=True):
        self.url, self.token = url.rstrip('/'), token
        self.timeout, self.verify = timeout, verify
        self.bearer = None
        self.lock = threading.Lock()

    def redact(self, text):
        for secret in (self.token, self.bearer):
            if secret:
                text = text.replace(secret, '[REDACTED]')
        return text

    def post(self, endpoint, headers, data=None):
        for attempt in range(4):
            try:
                response = requests.post(self.url + endpoint, headers=headers, data=data,
                                         timeout=self.timeout, verify=self.verify,
                                         allow_redirects=False)
            except requests.RequestException as exc:
                if attempt == 3:
                    raise RuntimeError(self.redact(str(exc))) from None
                time.sleep(2 ** attempt)
                continue
            if response.status_code == 200:
                return response
            print(self.redact(f'HTTP {response.status_code}: {response.text}'), file=sys.stderr)
            if (response.status_code == 429 or 500 <= response.status_code <= 599) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            return response

    def authenticate(self):
        response = self.post('/api/tokens/authenticate', {
            'Authorization': 'token ' + self.token,
            'Accept': 'application/vnd.blackducksoftware.user-4+json'})
        if response.status_code != 200:
            raise RuntimeError(f'authentication returned HTTP {response.status_code}')
        try:
            bearer = response.json()['bearerToken']
            if not isinstance(bearer, str) or not bearer:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise RuntimeError('authentication response has no valid bearerToken') from None
        self.bearer = bearer

    def match(self, text):
        for refresh in range(2):
            bearer = self.bearer
            response = self.post('/api/snippet-matching', {
                'Authorization': 'Bearer ' + bearer, 'Content-Type': 'text/plain',
                'Accept': ACCEPT}, text.encode('utf-8'))
            if response.status_code != 401 or refresh:
                return response
            with self.lock:
                if self.bearer == bearer:
                    self.authenticate()


def patterns(values):
    return [p.strip() for value in values for p in value.split(',') if p.strip()]


def discover(inputs, includes, excludes, out_dir):
    files, skipped, failed = set(), [], []
    def excluded(path):
        return any(fnmatch.fnmatchcase(path.name, p) or
                   fnmatch.fnmatchcase(path.as_posix(), p) for p in excludes)
    for value in inputs:
        root = Path(value).resolve()
        if not root.exists():
            failed.append((str(root), 'input does not exist'))
            continue
        if root.is_file():
            candidates = [root]
        else:
            candidates = []
            def walk_error(error):
                failed.append((str(error.filename), str(error)))
            for base, dirs, names in os.walk(root, onerror=walk_error):
                dirs[:] = sorted(d for d in dirs if not excluded(Path(base) / d)
                                  and (Path(base) / d).resolve() != out_dir)
                candidates.extend(Path(base) / name for name in sorted(names))
        for path in candidates:
            if out_dir == path or out_dir in path.parents or excluded(path):
                continue
            if not any(fnmatch.fnmatchcase(path.name, p) or
                       fnmatch.fnmatchcase(path.as_posix(), p) for p in includes):
                continue
            files.add(path)
    return sorted(files), skipped, failed


def read_source(path):
    data = path.read_bytes()
    if b'\0' in data:
        return None, len(data)
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return None, len(data)
    if any(ord(c) < 32 and c not in '\t\n\r\f\v' for c in text):
        return None, len(data)
    return text, len(data)


def write_reports(out, rows, skipped, failed, processed):
    with (out / 'results.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()
        # Prevent spreadsheet formula execution without altering raw JSON.
        writer.writerows({k: "'" + v if v.startswith(('=', '+', '-', '@')) else v
                          for k, v in row.items()} for row in rows)
    counts = Counter(row['license family'] for row in rows)
    lines = ['# Snippet matching summary', '',
             f'Processed: {processed}; match records: {len(rows)}; skipped: {len(skipped)}; failed: {len(failed)}',
             '', 'Counts are match records, not unique components or legal conclusions.', '',
             '| License family | Matches |', '| --- | ---: |']
    lines += [f'| {family} | {counts[family]} |' for family in FAMILIES]
    lines += ['', '## Files with matches', '']
    by_file = {}
    for row in rows:
        by_file.setdefault(row['file'], set()).add(row['license family'])
    def priority(file):
        return (not any(f.startswith('RECIPROCAL') or f == 'UNKNOWN'
                        for f in by_file[file]), file)
    lines += [f'- {json.dumps(file)}: {", ".join(sorted(by_file[file]))}'
              for file in sorted(by_file, key=priority)] or ['None.']
    for title, items in [('Skipped files', skipped), ('Failed files', failed)]:
        lines += ['', '## ' + title, '']
        lines += [f'- {json.dumps(file)}: {reason}' for file, reason in items] or ['None.']
    (out / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='+', help='Files or directories to check')
    parser.add_argument('--url', help='Server URL; BLACKDUCK_URL takes precedence')
    parser.add_argument('--token', help='API token; prefer BLACKDUCK_API_TOKEN (takes precedence)')
    parser.add_argument('--include', action='append', help='Comma-separated filename/path globs; repeatable; defaults to common source extensions')
    parser.add_argument('--exclude', action='append', default=['.git,node_modules,.venv,__pycache__'], help='Comma-separated filename/path globs to exclude; repeatable')
    parser.add_argument('--out-dir', default='snippet-output', help='Output directory (default: snippet-output)')
    parser.add_argument('--insecure', action='store_true', help='Disable TLS certificate verification; unsafe, off by default')
    parser.add_argument('--timeout', type=float, default=60, help='HTTP timeout in seconds (default: 60)')
    parser.add_argument('--workers', type=int, default=1, help='Concurrent file workers (default: 1)')
    parser.add_argument('--fail-on', help='Comma-separated license families that produce exit 1; other matches produce exit 0')
    parser.add_argument('--dry-run', action='store_true', help='List files, byte/non-whitespace sizes and chunks; no network calls')
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.workers < 1:
        parser.error('--timeout must be positive and --workers must be at least 1')
    gates = set(patterns([args.fail_on])) if args.fail_on is not None else set(FAMILIES)
    if not gates.issubset(FAMILIES):
        parser.error('--fail-on contains an unknown license family')
    out = Path(args.out_dir).resolve()
    files, skipped, failed = discover(args.paths, patterns(args.include or [DEFAULT_INCLUDE]),
                                      patterns(args.exclude), out)
    prepared = []
    for path in files:
        try:
            text, size = read_source(path)
            if text is None:
                skipped.append((str(path), 'binary or non-UTF-8 file'))
            elif non_whitespace(text) < MIN_CHARS:
                skipped.append((str(path), 'too small: fewer than 300 non-whitespace characters'))
            else:
                chunks = chunk_text(text)
                prepared.append((path, chunks))
                if args.dry_run:
                    print(f'{path}: {size} bytes, {non_whitespace(text)} non-whitespace characters, {len(chunks)} chunks')
        except (OSError, ValueError) as exc:
            failed.append((str(path), str(exc)))
    for path, reason in skipped + failed:
        print(f'{path}: {reason}')
    if args.dry_run:
        return 2 if failed else 0
    url = os.environ.get('BLACKDUCK_URL') or args.url
    token = os.environ.get('BLACKDUCK_API_TOKEN') or args.token
    if not url or not token:
        parser.error('set BLACKDUCK_URL and BLACKDUCK_API_TOKEN, or provide --url and --token')
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
        parser.error('--url must be an HTTP(S) server URL without credentials, query, or fragment')
    if args.insecure:
        print('WARNING: TLS certificate verification is disabled.', file=sys.stderr)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'raw').mkdir(exist_ok=True)
    client = Client(url, token, args.timeout, not args.insecure)
    rows = []
    try:
        if prepared:
            client.authenticate()
    except RuntimeError as exc:
        failed.extend((str(path), str(exc)) for path, _ in prepared)
        write_reports(out, rows, skipped, failed, 0)
        return 2

    def check(item):
        path, chunks = item
        file_rows, errors = [], []
        name = path.name + '-' + hashlib.sha256(str(path).encode()).hexdigest()[:16]
        for number, (text, offset) in enumerate(chunks, 1):
            raw_path = out / 'raw' / f'{name}.chunk-{number:04d}.json'
            try:
                response = client.match(text)
                # Store the untouched response body except credential redaction.
                raw_path.write_text(client.redact(response.text), encoding='utf-8')
                if response.status_code != 200:
                    raise ValueError(f'HTTP {response.status_code}; body saved in {raw_path.name}')
                file_rows.extend(parse_response(response.json(), path, offset))
            except (OSError, ValueError, RuntimeError) as exc:
                errors.append((str(path), f'chunk {number}: {client.redact(str(exc))}'))
        # Exact duplicate rows from overlapping chunks are removed.
        unique = {tuple(row[k] for k in FIELDS): row for row in file_rows}
        return list(unique.values()), errors
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for file_rows, errors in pool.map(check, prepared):
            rows.extend(file_rows)
            failed.extend(errors)
    write_reports(out, rows, skipped, failed, len(prepared))
    print(f'{len(rows)} matches; {len(skipped)} skipped; {len(failed)} errors. Reports: {out}')
    if failed:
        return 2
    return 1 if any(row['license family'] in gates for row in rows) else 0


if __name__ == '__main__':
    sys.exit(main())
