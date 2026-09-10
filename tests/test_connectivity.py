"""Portable behavior tests for the packaged connectivity comparison tool."""

from pathlib import Path
import json
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'circuit-schematic-wiring-simulation'
SCRIPT = SKILL / 'scripts' / 'compare_connectivity.py'


def document(*groups):
    return {'nets': [{'id': f'net-{i}', 'pins': list(group)} for i, group in enumerate(groups)]}


BASELINE = document(['U1.2', 'R1.1'], ['R1.2', 'U2.3'], ['U2.4'])


class ConnectivityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.before = self.directory / 'before.json'
        self.after = self.directory / 'after.json'
        self.report = self.directory / 'report.json'

    def compare(self, actual, code, expected=BASELINE, raw=False):
        self.before.write_text(json.dumps(expected), encoding='utf-8')
        self.after.write_text(actual if raw else json.dumps(actual), encoding='utf-8')
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.before), str(self.after), '--report', str(self.report)],
            capture_output=True, text=True, encoding='utf-8', timeout=15,
        )
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        parsed = json.loads(result.stderr if code == 2 else result.stdout)
        if code != 2:
            self.assertEqual(parsed, json.loads(self.report.read_text(encoding='utf-8')))
        return parsed

    def test_names_and_order_do_not_change_connectivity(self):
        changed = document(['U2.4'], ['U2.3', 'R1.2'], ['R1.1', 'U1.2'])
        for net in changed['nets']:
            net['id'] = 'unrelated-name'
        self.assertTrue(self.compare(changed, 0)['equivalent'])

    def test_open_wire(self):
        result = self.compare(document(['U1.2'], ['R1.1'], ['R1.2', 'U2.3'], ['U2.4']), 1)
        self.assertEqual(len(result['split_nets']), 1)
        self.assertEqual(result['merged_nets'], [])

    def test_short_between_networks(self):
        result = self.compare(document(['U1.2', 'R1.1', 'R1.2', 'U2.3'], ['U2.4']), 1)
        self.assertEqual(len(result['merged_nets']), 1)
        self.assertEqual(result['split_nets'], [])

    def test_wrong_pins_with_same_counts(self):
        result = self.compare(document(['U1.2', 'R1.2'], ['R1.1', 'U2.3'], ['U2.4']), 1)
        self.assertEqual(len(result['changed_pins']), 4)
        self.assertEqual(result['missing_pins'] + result['extra_pins'], [])

    def test_missing_connected_pin(self):
        result = self.compare(document(['U1.2'], ['R1.2', 'U2.3'], ['U2.4']), 1)
        self.assertEqual(result['missing_pins'], ['R1.1'])

    def test_missing_isolated_pin(self):
        result = self.compare(document(['U1.2', 'R1.1'], ['R1.2', 'U2.3']), 1)
        self.assertEqual(result['missing_pins'], ['U2.4'])

    def test_extra_pin(self):
        result = self.compare(document(['U1.2', 'R1.1'], ['R1.2', 'U2.3'], ['U2.4'], ['U3.1']), 1)
        self.assertEqual(result['extra_pins'], ['U3.1'])

    def test_duplicate_inside_network(self):
        self.compare(document(['U1.2', 'U1.2']), 2)

    def test_duplicate_across_networks(self):
        self.compare(document(['U1.2'], ['U1.2', 'R1.1']), 2)

    def test_empty_export(self):
        self.compare(document(), 2)

    def test_empty_network(self):
        self.compare(document([]), 2)

    def test_non_string_pin(self):
        self.compare(document([17]), 2)

    def test_blank_pin(self):
        self.compare(document([' ']), 2)

    def test_untrimmed_pin(self):
        self.compare(document([' U1.2']), 2)

    def test_malformed_json(self):
        self.compare('{', 2, raw=True)

    def test_wrong_document_shape(self):
        self.compare([], 2)

    def test_unicode_pin_identifiers(self):
        data = document(['传感器.输出', '电阻.1'], ['芯片.未接'])
        self.assertTrue(self.compare(data, 0, expected=data)['equivalent'])

    def test_report_cannot_overwrite_input(self):
        self.before.write_text(json.dumps(BASELINE), encoding='utf-8')
        original = self.before.read_bytes()
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.before), str(self.before), '--report', str(self.before)],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.before.read_bytes(), original)


class PackagingTests(unittest.TestCase):
    def test_skill_local_references_resolve(self):
        for markdown in SKILL.rglob('*.md'):
            for link in re.findall(r'\]\(([^)]+)\)', markdown.read_text(encoding='utf-8')):
                if '://' not in link:
                    self.assertTrue((markdown.parent / link.split('#')[0]).is_file(), link)

    def test_license_is_included_in_installable_folder(self):
        self.assertEqual((ROOT / 'LICENSE').read_bytes(), (SKILL / 'LICENSE').read_bytes())


if __name__ == '__main__':
    unittest.main()
