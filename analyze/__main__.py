"""CLI entry point: python -m analyze"""
import json
import sys
import threading

from analyze._ram import _sample_ram
from analyze.analysis import analyze_log
from analyze.args import parse_arguments
from analyze.filters import load_filters
from analyze.formatting import _deduplicate
from analyze.json_output import _build_json_output, json_output
from analyze.models import enum_criticality
from analyze.output import _stream_text_output


def main():
    args = parse_arguments()

    # Feature: --validate-filter (no log file needed)
    if args.validate_filter:
        try:
            load_filters(args.validate_filter)
            print(f"'{args.validate_filter}' is valid.")
            sys.exit(0)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    filter_groups = load_filters(args.filter)

    if args.watch and len(args.log_files) > 1:
        print("Error: --watch supports only a single file.", file=sys.stderr)
        sys.exit(1)

    multi_file = len(args.log_files) > 1

    if args.json:
        # JSON output buffers everything first (the format requires the filters
        # array to be emitted before matches, which needs the full scan result)
        ram_samples = []
        stop_event = threading.Event()
        sampler = threading.Thread(target=_sample_ram, args=(
            ram_samples, stop_event), daemon=True)
        sampler.start()

        total_lines = 0
        per_file_matches = []
        for log_file in args.log_files:
            line_counter = [0]
            file_matches = list(analyze_log(
                log_file, filter_groups, args.criticality, line_counter,
                context=args.context, max_matches=args.max_matches, watch=args.watch
            ))
            total_lines += line_counter[0]
            per_file_matches.append((log_file, file_matches, line_counter[0]))

        stop_event.set()
        sampler.join()

        if args.dedupe:
            per_file_matches = [
                (lf, _deduplicate(fm), lc) for lf, fm, lc in per_file_matches
            ]

        all_matches = [m for _, fm, _ in per_file_matches for m in fm]

        fail_triggered = False
        if args.fail_on:
            fail_threshold = enum_criticality[args.fail_on.upper()].value
            for _, name, criticality, _ in all_matches:
                if name is not None and enum_criticality[criticality.upper()].value >= fail_threshold:
                    fail_triggered = True
                    break

        if multi_file:
            file_docs = [
                _build_json_output(fm, [], stats=args.s, lines_scanned=lc, filename=lf)
                for lf, fm, lc in per_file_matches
            ]
            combined = {"files": file_docs}
            if args.s:
                combined["total_lines_scanned"] = total_lines
            print(json.dumps(combined, indent=2))
        else:
            json_output(all_matches, ram_samples, stats=args.s, lines_scanned=total_lines)

    else:
        # Text output: stream each match to stdout immediately as it is found
        fail_triggered = False
        for log_file in args.log_files:
            line_counter = [0]
            gen = analyze_log(
                log_file, filter_groups, args.criticality, line_counter,
                context=args.context, max_matches=args.max_matches, watch=args.watch
            )
            triggered = _stream_text_output(
                gen, filter_groups,
                stats=args.s,
                line_counter=line_counter,
                fail_on=args.fail_on,
                dedupe=args.dedupe,
                filename=log_file if multi_file else None,
            )
            fail_triggered = fail_triggered or triggered

    if fail_triggered:
        sys.exit(1)


if __name__ == "__main__":
    main()
