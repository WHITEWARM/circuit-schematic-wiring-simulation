#!/usr/bin/env python3
"""Compare external-pin partitions exported independently from circuit sources.

This tool does not parse EDA files, inspect geometry, or run a simulator.
Exit codes: 0 equivalent, 1 different, 2 invalid input or file error.
"""

import argparse
import json
from pathlib import Path
import sys


def read_partition(path):
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError(f"{path}: top level must be an object")
    nets = document.get("nets")
    if not isinstance(nets, list) or not nets:
        raise ValueError(f"{path}: nets must be a nonempty array")

    groups = set()
    by_pin = {}
    for index, net in enumerate(nets):
        if not isinstance(net, dict):
            raise ValueError(f"{path}: nets[{index}] must be an object")
        pins = net.get("pins")
        if not isinstance(pins, list) or not pins:
            raise ValueError(f"{path}: nets[{index}].pins must be a nonempty array")
        for pin in pins:
            if not isinstance(pin, str) or not pin.strip() or pin != pin.strip():
                raise ValueError(f"{path}: pin names must be nonempty trimmed strings")
        group = frozenset(pins)
        if len(group) != len(pins):
            raise ValueError(f"{path}: duplicate pin within nets[{index}]")
        for pin in pins:
            if pin in by_pin:
                raise ValueError(f"{path}: pin {pin!r} belongs to multiple nets")
            by_pin[pin] = group
        groups.add(group)
    return groups, by_pin


def ordered_groups(groups):
    return sorted(sorted(group) for group in groups)


def compare_partitions(before, after):
    old_groups, old_pins = before
    new_groups, new_pins = after
    old_set, new_set = set(old_pins), set(new_pins)
    shared = old_set & new_set

    splits = []
    for group in sorted(old_groups, key=lambda value: sorted(value)):
        targets = {new_pins[pin] for pin in group & shared}
        if len(targets) > 1:
            splits.append({"before": sorted(group), "after": ordered_groups(targets)})

    merges = []
    for group in sorted(new_groups, key=lambda value: sorted(value)):
        sources = {old_pins[pin] for pin in group & shared}
        if len(sources) > 1:
            merges.append({"before": ordered_groups(sources), "after": sorted(group)})

    changed = [
        {
            "pin": pin,
            "before_peers": sorted(old_pins[pin] - {pin}),
            "after_peers": sorted(new_pins[pin] - {pin}),
        }
        for pin in sorted(shared)
        if old_pins[pin] != new_pins[pin]
    ]
    return {
        "equivalent": old_groups == new_groups,
        "scope": "External pin grouping only; geometry, models and simulation are not checked.",
        "before": {"pins": len(old_pins), "nets": len(old_groups)},
        "after": {"pins": len(new_pins), "nets": len(new_groups)},
        "missing_pins": sorted(old_set - new_set),
        "extra_pins": sorted(new_set - old_set),
        "split_nets": splits,
        "merged_nets": merges,
        "changed_pins": changed,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path, help="Expected or baseline pin-group JSON")
    parser.add_argument("after", type=Path, help="Independently exported comparison JSON")
    parser.add_argument("--report", type=Path, help="Write the comparison report as UTF-8 JSON")
    args = parser.parse_args(argv)
    try:
        if args.report and args.report.resolve() in {args.before.resolve(), args.after.resolve()}:
            raise ValueError("Report path must not overwrite an input file")
        result = compare_partitions(read_partition(args.before), read_partition(args.after))
        result["sources"] = {"before": str(args.before.resolve()), "after": str(args.after.resolve())}
        payload = json.dumps(result, ensure_ascii=True, indent=2) + "\n"
        if args.report:
            args.report.write_text(payload, encoding="utf-8")
        sys.stdout.write(payload)
        return 0 if result["equivalent"] else 1
    except (OSError, UnicodeError, ValueError) as error:
        sys.stderr.write(json.dumps({"error": str(error)}, ensure_ascii=True) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
