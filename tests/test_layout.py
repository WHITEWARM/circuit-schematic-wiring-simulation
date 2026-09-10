"""Behavior tests for the portable geometric audit; no Multisim installation needed."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/circuit-schematic-wiring-simulation/scripts/audit_layout.py'
SPEC = importlib.util.spec_from_file_location('layout_audit', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def wire(identifier, a, b, net='N1'):
    return {'id': identifier, 'a': a, 'b': b, 'net': net}


BASE = {'source': 'fixture-native-export:revision-1', 'canvas': [0, 0, 100, 100],
        'min_wire_gap': 3, 'min_font_size_pt': 8,
        'segments': [wire('W1', [10, 10], [30, 10])],
        'bodies': [{'id': 'U1', 'box': [30, 5, 40, 15]}],
        'labels': [{'id': 'U1-label', 'box': [30, 20, 40, 25], 'font_size_pt': 9}]}


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.data = copy.deepcopy(BASE)

    def codes(self):
        return [f['code'] for f in MODULE.audit(self.data)['findings']]

    def test_clean_geometry_still_requires_native_and_render_review(self):
        result = MODULE.audit(self.data)
        self.assertTrue(result['geometry_clear'])
        self.assertEqual(result['native_connectivity'], 'not_checked')
        self.assertEqual(result['rendered_readability'], 'not_checked')
        self.assertEqual(result['export_completeness'], 'not_verified')

    def test_reverse_duplicate(self):
        self.data['segments'].append(wire('W2', [30, 10], [10, 10]))
        self.assertIn('duplicate_wire', self.codes())

    def test_same_net_partial_overlap(self):
        self.data['segments'].append(wire('W2', [15, 10], [25, 10]))
        self.assertIn('overlapping_same_net', self.codes())

    def test_different_net_overlap(self):
        self.data['segments'].append(wire('W2', [15, 10], [25, 10], 'N2'))
        self.assertIn('overlapping_different_nets', self.codes())

    def test_shared_endpoint_is_allowed(self):
        self.data['segments'].append(wire('W2', [0, 10], [10, 10]))
        self.assertEqual(self.codes(), [])

    def test_vertical_duplicate(self):
        self.data['segments'] = [wire('W1', [10, 10], [10, 30]), wire('W2', [10, 30], [10, 10])]
        self.assertIn('duplicate_wire', self.codes())

    def test_outside_canvas(self):
        self.data['segments'][0]['a'][0] = -1
        self.assertIn('outside_canvas', self.codes())

    def test_zero_length(self):
        self.data['segments'][0]['b'] = [10, 10]
        self.assertIn('zero_length_wire', self.codes())

    def test_wire_body_penetration(self):
        self.data['segments'][0]['b'][0] = 35
        self.assertIn('wire_through_body', self.codes())

    def test_wire_label_penetration(self):
        self.data['labels'][0]['box'] = [15, 9, 20, 11]
        self.assertIn('wire_through_label', self.codes())

    def test_parallel_gap(self):
        self.data['segments'].append(wire('W2', [10, 12], [20, 12], 'N2'))
        self.assertIn('parallel_wires_too_close', self.codes())

    def test_parallel_nonoverlapping_projection_is_clear(self):
        self.data['segments'].append(wire('W2', [1, 12], [5, 12], 'N2'))
        self.assertEqual(self.codes(), [])

    def test_crossing_is_review_item_not_proven_short(self):
        self.data['segments'].append(wire('W2', [20, 0], [20, 20], 'N2'))
        self.assertEqual(self.codes(), ['crossing_needs_visual_review'])

    def test_body_overlap(self):
        self.data['bodies'].append({'id': 'U2', 'box': [35, 5, 45, 15]})
        self.assertIn('overlapping_bodies', self.codes())

    def test_label_overlap(self):
        self.data['labels'].append({'id': 'L2', 'box': [35, 20, 45, 25], 'font_size_pt': 9})
        self.assertIn('overlapping_labels', self.codes())

    def test_font_small_or_unknown(self):
        self.data['labels'][0]['font_size_pt'] = 6
        self.assertIn('font_too_small', self.codes())
        del self.data['labels'][0]['font_size_pt']
        self.assertIn('font_size_not_exported', self.codes())

    def test_invalid_exports_fail_closed(self):
        invalid = []
        for collection in ('segments', 'bodies', 'labels'):
            value = copy.deepcopy(BASE)
            del value[collection]
            invalid.append(value)
        for bad in (True, float('nan'), float('inf'), '1'):
            value = copy.deepcopy(BASE)
            value['segments'][0]['a'][0] = bad
            invalid.append(value)
        diagonal = copy.deepcopy(BASE)
        diagonal['segments'][0]['b'] = [30, 11]
        invalid.append(diagonal)
        duplicate = copy.deepcopy(BASE)
        duplicate['labels'][0]['id'] = 'W1'
        invalid.append(duplicate)
        empty = copy.deepcopy(BASE)
        empty['segments'] = []
        invalid.append(empty)
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    MODULE.audit(value)

    def test_cli_report_exit_codes_and_input_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            source, report = Path(directory) / 'geometry.json', Path(directory) / 'report.json'
            for expected in (0, 1, 2):
                if expected == 1:
                    self.data['segments'].append(wire('W2', [10, 10], [30, 10]))
                source.write_text('{' if expected == 2 else json.dumps(self.data), encoding='utf-8')
                result = subprocess.run([sys.executable, str(SCRIPT), str(source), '--report', str(report)],
                                        capture_output=True, text=True, encoding='utf-8', timeout=15)
                self.assertEqual(result.returncode, expected, result.stderr)
                if expected != 2:
                    self.assertEqual(json.loads(result.stdout), json.loads(report.read_text(encoding='utf-8')))
            original = source.read_bytes()
            result = subprocess.run([sys.executable, str(SCRIPT), str(source), '--report', str(source)],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
