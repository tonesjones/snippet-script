import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import snippet_check as sc

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/snippet-response.json').read_text(encoding='utf-8'))

def response(status=200, payload=None):
    r = Mock(status_code=status, text=json.dumps((payload if payload is not None else FIXTURE) if status == 200 else {'error': 'test error'}))
    r.json.return_value = payload if payload is not None else FIXTURE
    return r

class Tests(unittest.TestCase):
    def test_count_unicode_whitespace(self):
        self.assertEqual(sc.non_whitespace('a \t\n\r\u2003b'), 2)

    def test_chunks_cover_lines_and_map_offsets(self):
        lines = ['x' * 1000 + '\n'] * 101
        chunks = sc.chunk_text(''.join(lines))
        covered = set()
        for text, offset in chunks:
            self.assertTrue(300 <= sc.non_whitespace(text) <= 50000)
            self.assertEqual(text, ''.join(lines[offset:offset + len(text.splitlines())]))
            covered.update(range(offset, offset + len(text.splitlines())))
        self.assertEqual(covered, set(range(101)))
        self.assertEqual([offset for _, offset in chunks], [0, 50, 100])

    def test_short_tail_overlaps(self):
        chunks = sc.chunk_text(('x' * 25000 + '\n') * 2 + 'y' * 200)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[1][1], 1)
        self.assertEqual(sc.non_whitespace(chunks[1][0]), 25200)

    def test_long_line_rejected(self):
        with self.assertRaises(ValueError):
            sc.chunk_text('x' * 50001)

    def test_boundaries(self):
        self.assertEqual(len(sc.chunk_text('x' * 50000)), 1)
        self.assertEqual(sc.non_whitespace(sc.chunk_text('x' * 300)[0][0]), 300)

    def test_live_fixture_and_line_mapping(self):
        rows = sc.parse_response(FIXTURE, 'sample.java', 100)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]['source lines'], '119-165')
        self.assertEqual(rows[0]['matched lines'], '36-69')
        self.assertEqual(rows[0]['license family'], 'UNKNOWN')
        self.assertEqual(rows[1]['license'], 'GNU General Public License v2.0 or later')

    def test_multiple_regions_and_license_fallback(self):
        payload = json.loads(json.dumps(FIXTURE))
        m = payload['snippetMatches']['UNKNOWN'][0]
        m['regions'] = dict(sourceStartLines=[1, 10], sourceEndLines=[3, 12],
                            matchedStartLines=[5, 20], matchedEndLines=[7, 22])
        m['licenseDefinition'] = {'spdxId': 'Example'}
        row = sc.parse_response(payload, 'a', 20)[0]
        self.assertEqual(row['source lines'], '21-23; 30-32')
        self.assertEqual(row['license'], 'Example')

    def test_empty_and_malformed(self):
        self.assertEqual(sc.parse_response({'snippetMatches': {}}, 'a'), [])
        for payload in ({}, {'snippetMatches': []}, {'snippetMatches': {'NEW': []}},
                        {'snippetMatches': {'UNKNOWN': [{}]}}):
            with self.assertRaises(ValueError): sc.parse_response(payload, 'a')

    @patch('snippet_check.time.sleep')
    @patch('snippet_check.requests.post')
    def test_http_retry_refresh_and_headers(self, post, sleep):
        post.side_effect = [response(payload={'bearerToken': 'first'}), response(401),
                            response(payload={'bearerToken': 'second'}), response(429), response()]
        c = sc.Client('https://example.invalid', 'secret')
        c.authenticate()
        self.assertEqual(c.match('abc').status_code, 200)
        self.assertEqual(post.call_count, 5)
        call = post.call_args
        self.assertEqual(call.kwargs['data'], b'abc')
        self.assertEqual(call.kwargs['headers']['Authorization'], 'Bearer second')
        self.assertFalse(call.kwargs['allow_redirects'])
        self.assertTrue(call.kwargs['verify'])
        sleep.assert_called_once_with(1)

    @patch('snippet_check.requests.post')
    def test_reports_and_exit_codes(self, post):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            p = Path(tmp) / 'a.py'; p.write_text('x' * 400)
            out = Path(tmp) / 'out'
            post.side_effect = [response(payload={'bearerToken': 'bearer'}), response()]
            self.assertEqual(sc.main(['--url', 'https://example.invalid', '--token', 'secret',
                                      '--out-dir', str(out), str(p)]), 1)
            self.assertEqual(len(list((out / 'raw').glob('*.json'))), 1)
            self.assertIn('RECIPROCAL', (out / 'summary.md').read_text())
            post.side_effect = [response(payload={'bearerToken': 'bearer'}), response(payload={'snippetMatches': {}})]
            self.assertEqual(sc.main(['--url', 'https://example.invalid', '--token', 'secret',
                                      '--out-dir', str(out), str(p)]), 0)
            post.side_effect = [response(payload={'bearerToken': 'bearer'}), response(payload={})]
            self.assertEqual(sc.main(['--url', 'https://example.invalid', '--token', 'secret',
                                      '--out-dir', str(out), str(p)]), 2)

    @patch('snippet_check.requests.post')
    def test_dry_run_no_http(self, post):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            p = Path(tmp)
            (p / 'valid.py').write_text('x' * 400)
            (p / 'small.py').write_text('x')
            (p / 'binary.c').write_bytes(b'\0' * 400)
            self.assertEqual(sc.main(['--dry-run', tmp]), 0)
            post.assert_not_called()


    @patch('snippet_check.time.sleep')
    @patch('snippet_check.requests.post')
    def test_exhausted_5xx_and_redaction(self, post, sleep):
        post.side_effect = [response(503)] * 4
        c = sc.Client('https://example.invalid', 'secret')
        self.assertEqual(c.post('/api/test', {}).status_code, 503)
        self.assertEqual(post.call_count, 4)
        self.assertEqual([v.args[0] for v in sleep.call_args_list], [1, 2, 4])
        self.assertEqual(c.redact('secret'), '[REDACTED]')

    def test_impossible_tail_rejected(self):
        with self.assertRaises(ValueError):
            sc.chunk_text('x' * 49900 + '\n' + 'y' * 200)

    @patch('snippet_check.requests.post')
    def test_gate_ignores_other_families(self, post):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            p = Path(tmp) / 'a.py'; p.write_text('x' * 400)
            post.side_effect = [response(payload={'bearerToken': 'bearer'}), response()]
            self.assertEqual(sc.main(['--url', 'https://example.invalid', '--token', 'secret',
                                      '--fail-on', 'PERMISSIVE', '--out-dir', str(Path(tmp) / 'out'), str(p)]), 0)


    def test_lf_and_crlf_chunk_offsets(self):
        for newline in ('\n', '\r\n'):
            with self.subTest(newline=repr(newline)):
                text = ('x' * 1000 + newline) * 60
                chunks = sc.chunk_text(text)
                self.assertEqual([offset for _, offset in chunks], [0, 50])
                self.assertEqual(''.join(chunk for chunk, _ in chunks), text)
                row = sc.parse_response(FIXTURE, 'example.java', chunks[1][1])[0]
                self.assertEqual(row['source lines'], '69-115')

    def test_utf8_bom_unicode_paths_and_filters(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            root = Path(tmp) / 'Project with spaces'
            root.mkdir()
            source = root / 'café.py'
            source.write_bytes(b'\xef\xbb\xbf' + ('# café\n' * 100).encode('utf-8'))
            excluded = root / 'generated'
            excluded.mkdir()
            (excluded / 'skip.py').write_text('x' * 400, encoding='utf-8')
            out = root / 'output'
            out.mkdir()
            (out / 'skip.py').write_text('x' * 400, encoding='utf-8')
            files, _, failed = sc.discover([str(root)], ['*.py'], ['generated'], out.resolve())
            self.assertEqual(files, [source.resolve()])
            self.assertEqual(failed, [])
            text, size = sc.read_source(source)
            self.assertEqual(text, '# café\n' * 100)
            self.assertEqual(size, len(source.read_bytes()))
            rows = sc.parse_response(FIXTURE, source)
            sc.write_reports(out, rows, [], [], 1)
            import csv
            with (out / 'results.csv').open(encoding='utf-8', newline='') as f:
                saved = list(csv.DictReader(f))
            self.assertEqual(saved[0]['file'], str(source))

    @patch('snippet_check.requests.post')
    @patch('snippet_check.getpass.getpass', return_value='secret')
    @patch('builtins.input', return_value='https://example.invalid')
    @patch('snippet_check.sys.stdin')
    def test_prompts_for_missing_credentials(self, stdin, ask, getpw, post):
        stdin.isatty.return_value = True
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp,                 patch.dict('os.environ', {}, clear=True), patch('sys.stdout'):
            p = Path(tmp) / 'a.py'; p.write_text('x' * 400)
            post.side_effect = [response(payload={'bearerToken': 'bearer'}), response()]
            self.assertEqual(sc.main(['--out-dir', str(Path(tmp) / 'out'), str(p)]), 1)
            ask.assert_called_once(); getpw.assert_called_once()
            self.assertEqual(post.call_args_list[0].args[0], 'https://example.invalid/api/tokens/authenticate')

    @patch('snippet_check.sys.stdin')
    def test_no_prompt_without_tty(self, stdin):
        stdin.isatty.return_value = False
        with patch.dict('os.environ', {}, clear=True), patch('sys.stderr'),                 tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            p = Path(tmp) / 'a.py'; p.write_text('x' * 400)
            with self.assertRaises(SystemExit):
                sc.main([str(p)])

    def test_console_summary(self):
        rows = [{'file': f'f{i}', 'license family': 'RECIPROCAL'} for i in range(12)]
        rows.append({'file': 'p', 'license family': 'PERMISSIVE'})
        with patch('builtins.print') as out:
            sc.print_summary(rows)
        text = '\n'.join(str(c.args[0]) for c in out.call_args_list)
        self.assertIn('RECIPROCAL: 12', text)
        self.assertIn('PERMISSIVE: 1', text)
        self.assertIn('...and 2 more', text)
        self.assertNotIn('  p', text)

if __name__ == '__main__': unittest.main()
