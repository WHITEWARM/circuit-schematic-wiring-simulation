"""Audit exported orthogonal schematic geometry; does not parse or modify EDA files."""

import argparse
import itertools
import json
import math
from pathlib import Path
import sys

EPS = 1e-8


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Coordinates and thresholds must be finite numbers.')
    return value


def vector(value, length):
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f'Expected a list of {length} numbers.')
    return [number(v) for v in value]


def box(value):
    b = vector(value, 4)
    if b[0] >= b[2] or b[1] >= b[3]:
        raise ValueError('Boxes must have positive width and height: [left, top, right, bottom].')
    return b


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object.')
    box(data.get('canvas'))
    if not isinstance(data.get('source'), str) or not data['source'].strip():
        raise ValueError('source must identify the native export and its version/hash.')
    seen = set()
    for collection in ('segments', 'bodies', 'labels'):
        rows = data.get(collection)
        if not isinstance(rows, list) or (collection == 'segments' and not rows):
            raise ValueError(f'{collection} must be a list; segments must not be empty.')
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Each geometry object must be a JSON object.')
            identifier = row.get('id')
            if not isinstance(identifier, str) or not identifier or identifier.strip() != identifier:
                raise ValueError('Each object needs a nonempty trimmed id.')
            if identifier in seen:
                raise ValueError(f'Duplicate object id: {identifier}')
            seen.add(identifier)
            if collection == 'segments':
                a, b = vector(row.get('a'), 2), vector(row.get('b'), 2)
                if a[0] != b[0] and a[1] != b[1]:
                    raise ValueError(f'{identifier}: export orthogonal straight segments only.')
                net = row.get('net')
                if not isinstance(net, str) or not net or net.strip() != net:
                    raise ValueError(f'{identifier}: net must be a nonempty trimmed string.')
            else:
                box(row.get('box'))
                if collection == 'labels' and 'font_size_pt' in row:
                    if number(row['font_size_pt']) <= 0:
                        raise ValueError('font_size_pt must be positive.')
    for key in ('min_wire_gap', 'min_font_size_pt'):
        if number(data.get(key, 0)) < 0:
            raise ValueError(f'{key} cannot be negative.')
    return data


def segment_info(s):
    a, b = s['a'], s['b']
    horizontal = a[1] == b[1]
    axis = 0 if horizontal else 1
    return horizontal, a[1 - axis], min(a[axis], b[axis]), max(a[axis], b[axis])


def box_overlap(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > EPS and min(a[3], b[3]) - max(a[1], b[1]) > EPS


def hits_box(s, b):
    horizontal, fixed, lo, hi = segment_info(s)
    if horizontal:
        return b[1] + EPS < fixed < b[3] - EPS and min(hi, b[2]) - max(lo, b[0]) > EPS
    return b[0] + EPS < fixed < b[2] - EPS and min(hi, b[3]) - max(lo, b[1]) > EPS


def audit(document):
    d = validate(document)
    findings = []

    def add(code, *objects, **details):
        findings.append({'code': code, 'objects': list(objects), **details})

    page = d['canvas']
    segments = d['segments']
    for collection in ('segments', 'bodies', 'labels'):
        for row in d[collection]:
            points = (row['a'], row['b']) if collection == 'segments' else (row['box'][:2], row['box'][2:])
            if any(p[0] < page[0] - EPS or p[0] > page[2] + EPS or p[1] < page[1] - EPS or p[1] > page[3] + EPS for p in points):
                add('outside_canvas', row['id'])
    for s in segments:
        if s['a'] == s['b']:
            add('zero_length_wire', s['id'])
        for collection, code in (('bodies', 'wire_through_body'), ('labels', 'wire_through_label')):
            for b in d[collection]:
                if hits_box(s, b['box']):
                    add(code, s['id'], b['id'])

    for a, b in itertools.combinations(segments, 2):
        ah, af, alo, ahi = segment_info(a)
        bh, bf, blo, bhi = segment_info(b)
        if ah == bh:
            overlap = min(ahi, bhi) - max(alo, blo)
            if overlap <= EPS:
                continue  # End-to-end segments are not duplicate wires.
            gap = abs(af - bf)
            if gap <= EPS:
                code = 'overlapping_same_net' if a['net'] == b['net'] else 'overlapping_different_nets'
                if a['net'] == b['net'] and abs(alo - blo) <= EPS and abs(ahi - bhi) <= EPS:
                    code = 'duplicate_wire'
                add(code, a['id'], b['id'])
            elif gap < d.get('min_wire_gap', 0) - EPS:
                add('parallel_wires_too_close', a['id'], b['id'], gap=gap)
        elif a['net'] != b['net']:
            h, v = (a, b) if ah else (b, a)
            _, y, left, right = segment_info(h)
            _, x, top, bottom = segment_info(v)
            if left - EPS <= x <= right + EPS and top - EPS <= y <= bottom + EPS:
                add('crossing_needs_visual_review', a['id'], b['id'], point=[x, y])

    for collection, code in (('bodies', 'overlapping_bodies'), ('labels', 'overlapping_labels')):
        for a, b in itertools.combinations(d[collection], 2):
            if box_overlap(a['box'], b['box']):
                add(code, a['id'], b['id'])
    for label in d['labels']:
        if d.get('min_font_size_pt', 0):
            size = label.get('font_size_pt')
            if size is None:
                add('font_size_not_exported', label['id'])
            elif size < d['min_font_size_pt']:
                add('font_too_small', label['id'], font_size_pt=size)

    return {
        'source': d['source'],
        'scope': 'exported_orthogonal_geometry_only',
        'native_connectivity': 'not_checked',
        'rendered_readability': 'not_checked',
        'export_completeness': 'not_verified',
        'thresholds': {k: d.get(k, 0) for k in ('min_wire_gap', 'min_font_size_pt')},
        'object_counts': {k: len(d[k]) for k in ('segments', 'bodies', 'labels')},
        'geometry_clear': not findings,
        'findings': findings,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('geometry', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        if args.report and (args.report.resolve() == args.geometry.resolve() or
                            (args.report.exists() and args.report.samefile(args.geometry))):
            raise ValueError('Report must not overwrite the input file.')
        result = audit(json.loads(args.geometry.read_text(encoding='utf-8-sig')))
        encoded = json.dumps(result, ensure_ascii=False, indent=2)
        if args.report:
            args.report.write_text(encoded + '\n', encoding='utf-8')
        print(encoded)
        return 0 if result['geometry_clear'] else 1
    except (ValueError, OSError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
