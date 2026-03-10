"""
Automatic Log Analyzer

Streams a log file line-by-line and reports lines that match configurable
filter groups. Supports plain substring matching and regular expressions,
with optional case sensitivity and word-boundary constraints.

Usage:
    python analyze.py <log_file> [--filter FILE] [--criticality LEVEL] [-s] [--json]
"""
import argparse
import json
import re
from collections import namedtuple, Counter
from enum import Enum
import threading
from time import sleep
import tracemalloc

import jsonschema

COLORS = {
    "reset": "\033[0m",
    "high": "\033[31m",
    "medium": "\033[33m",
    "low": "\033[37m"
}

enum_criticality = Enum("Criticality", ["LOW", "MEDIUM", "HIGH"])

_FILTER_SCHEMA = {
    "type": "array", "minItems": 1,
    "items": {
        "type": "object",
        "required": ["name", "filters", "criticality"],
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "criticality": {"type": "string", "enum": ["low", "medium", "high"]},
            "filters": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["filter", "regex", "case_sensitive", "word_match"],
                    "additionalProperties": False,
                    "properties": {
                        "filter": {"type": "string", "minLength": 1},
                        "regex": {"type": "boolean"},
                        "case_sensitive": {"type": "boolean"},
                        "word_match": {"type": "boolean"}
                    }
                }
            }
        }
    }
}

filters_file = "filter.json"

FilterGroup = namedtuple("FilterGroup", ["name", "criticality", "filters"])


def _sample_ram(samples, stop_event, interval=0.01):
    """Sample current traced-memory usage at a regular interval.

    Intended to run in a daemon thread. Appends byte counts to `samples`
    until `stop_event` is set.

    Args:
        samples (list): Mutable list to append memory readings (bytes) to.
        stop_event (threading.Event): Signal to stop sampling.
        interval (float): Seconds between samples. Defaults to 0.01.
    """
    tracemalloc.start()
    while not stop_event.is_set():
        current, _ = tracemalloc.get_traced_memory()
        samples.append(current)
        sleep(interval)
    tracemalloc.stop()


class Filter:
    """Compiled representation of a single filter rule.

    Attributes:
        filter (str): The search string or regex pattern.
        regex (bool): If True, treat `filter` as a regular expression.
        case_sensitive (bool): If True, matching is case-sensitive.
        word_match (bool): If True, only match at word boundaries.
    """

    def __init__(self, filter, regex, case_sensitive, word_match):
        self.filter = filter
        self.regex = regex
        self.case_sensitive = case_sensitive
        self.word_match = word_match

    def match(self, log_line):
        flags = 0 if self.case_sensitive else re.IGNORECASE
        if self.regex:
            pat = rf"\b{self.filter}\b" if self.word_match else self.filter
        else:
            pat = rf"\b{re.escape(self.filter)}\b" if self.word_match else re.escape(
                self.filter)
        return bool(re.search(pat, log_line, flags))


def load_filters(filters_file):
    """Load filter groups from a JSON configuration file.

    Args:
        filters_file (str): Path to the JSON filter configuration file.

    Returns:
        list[FilterGroup]: Parsed filter groups with their Filter objects.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
        jsonschema.ValidationError: If the file does not conform to the filter schema.
        re.error: If a filter with regex=True contains an invalid regular expression.
    """
    with open(filters_file, "r") as f:
        data = json.load(f)
    jsonschema.validate(data, _FILTER_SCHEMA)
    for group in data:
        for filt in group["filters"]:
            if filt["regex"]:
                re.compile(filt["filter"])
    groups = []
    for group in data:
        filter_objs = [
            Filter(f["filter"], f["regex"],
                   f["case_sensitive"], f["word_match"])
            for f in group["filters"]
        ]
        groups.append(FilterGroup(
            group["name"], group["criticality"], filter_objs))
    return groups


def analyze_log(log_file, filter_groups, criticality, line_counter):
    """Stream a log file and yield lines that match any filter group.

    Reads the file one line at a time, keeping memory usage constant
    regardless of file size.

    Args:
        log_file (str): Path to the log file to analyze.
        filter_groups (list[FilterGroup]): Filter groups to apply.
        criticality (str): Minimum criticality level to report
            ('high', 'medium', or 'low').
        line_counter (list[int]): Single-element list updated with the
            current line number as the file is read.

    Yields:
        tuple[int, str, str, str]: (line_number, group_name, criticality, line_text)

    Raises:
        FileNotFoundError: If the log file does not exist.
    """
    with open(log_file, "r", errors="replace") as f:
        for line_num, line in enumerate(f, start=1):
            line_counter[0] = line_num
            line = line.rstrip("\n")
            for group in filter_groups:
                for filt in group.filters:
                    if filt.match(line):
                        if enum_criticality[group.criticality.upper()].value >= enum_criticality[criticality.upper()].value:
                            yield line_num, group.name, group.criticality, line
                        break  # one match per group per line is enough


def json_output(matches, ram_samples, stats=False, lines_scanned=0):
    """Print analysis results as a JSON document.

    Each filter name appears once in "filters"; matches reference filters
    by integer ID. Optionally includes a "stats" block.

    Args:
        matches (list[tuple]): List of (line_num, name, criticality, line) tuples.
        ram_samples (list[int]): Memory samples in bytes from _sample_ram.
        stats (bool): If True, include a stats block in the output.
        lines_scanned (int): Total lines read from the log file.
    """
    filter_map = {}  # name -> id
    match_counts = Counter()

    for _, name, criticality, _ in matches:
        if name not in filter_map:
            filter_map[name] = {
                "id": len(filter_map),
                "criticality": criticality
            }
        match_counts[(filter_map[name]["id"])] += 1

    output_json = {
        "filters": [{"id": data["id"], "name": name, "criticality": data["criticality"]} for name, data in filter_map.items()],
        "matches": [
            {
                "filter_id": filter_map[name]["id"],
                "line_number": line_num,
                "text": line,
            }
            for line_num, name, _, line in matches
        ],
    }
    if stats:
        total_matches = sum(match_counts.values())

        output_json.update(
            {
                "stats": {
                    "lines_scanned": lines_scanned,
                    "total_matches": total_matches,
                    "filter_matches": [
                        {
                            "id": match_id,
                            "count": count
                        } for match_id, count in match_counts.items()
                    ]
                }
            }
        )
        if ram_samples:
            ram_samples = ram_samples[1:] if ram_samples[0] == 0 else ram_samples
            to_kb = 1 / 1024
            min_ram = min(ram_samples) * to_kb
            max_ram = max(ram_samples) * to_kb
            avg_ram = sum(ram_samples) / len(ram_samples) * to_kb

            output_json.update(
                {
                    "stats": {
                        "ram_usage": {
                            "min": min_ram,
                            "avg": avg_ram,
                            "max": max_ram,
                            "unit": "kb"
                        }
                    }
                }
            )
    print(json.dumps(output_json, indent=2))


def user_output(matches, ram_samples, filter_groups, stats=False, lines_scanned=0):
    """Print analysis results as aligned, color-coded text.

    Column widths are derived from the widest values in the result set so
    all columns line up regardless of data.

    Args:
        matches (list[tuple]): List of (line_num, name, criticality, line) tuples.
        ram_samples (list[int]): Memory samples in bytes from _sample_ram.
        filter_groups (list[FilterGroup]): Loaded filter groups (used to
            compute the maximum filter name width for padding).
        stats (bool): If True, print a stats summary after the matches.
        lines_scanned (int): Total lines read from the log file.
    """
    name_width = max((len(g.name) for g in filter_groups), default=0)
    crit_width = max(len(e.name) for e in enum_criticality)
    line_num_width = len(str(matches[-1][0])) if matches else 1
    match_counts = Counter()

    for line_num, name, criticality, line in matches:
        match_counts[(name, criticality)] += 1
        color = COLORS.get(criticality.lower(), "")
        criticality_text = f"{color}{criticality.upper():{crit_width}}{COLORS['reset']}"
        print(
            f"{COLORS['low']}l{line_num:{line_num_width}}{COLORS['reset']} [{criticality_text}] ({name:{name_width}}): {line}")

    if stats:
        total_matches = sum(match_counts.values())
        print(f"\n--- Stats ---")
        print(f"Lines scanned : {lines_scanned}")
        print(f"Total matches : {total_matches}")
        for (name, crit), count in match_counts.items():
            color = COLORS.get(crit.lower(), "")
            print(
                f"  {color}{crit.upper():{crit_width}}{COLORS['reset']} ({name:{name_width}}): {count}")
        if ram_samples:
            ram_samples = ram_samples[1:] if ram_samples[0] == 0 else ram_samples
            to_kb = 1 / 1024
            min_ram = min(ram_samples) * to_kb
            max_ram = max(ram_samples) * to_kb
            avg_ram = sum(ram_samples) / len(ram_samples) * to_kb
            print()
            print(
                f"RAM: {min_ram:.1f} KB | {avg_ram:.1f} KB | {max_ram:.1f} KB")


def parse_arguments():
    """Parse and validate command-line arguments.

    Prints help and exits with code 1 if no log file is provided.
    Argparse enforces valid choices for --criticality.

    Returns:
        argparse.Namespace: Parsed arguments with attributes:
            log_file (str), filter (str), criticality (str), s (bool), json (bool).
    """
    parser = argparse.ArgumentParser(description="Analyze logs")
    parser.add_argument("log_file", type=str,
                        help="Path to the log file to analyze",
                        nargs="?")
    parser.add_argument("--filter", type=str,
                        default=filters_file,
                        help="Path to filter configuration JSON file (default: filter.json)")
    parser.add_argument("--criticality", type=str,
                        default="HIGH",
                        help="Minimum criticality level to report: high, medium, or low (default: high)",
                        choices=[e.name.lower() for e in enum_criticality])
    parser.add_argument("-s", action="store_true",
                        help="Print a stats summary after analysis (line count, match count, RAM usage)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON instead of colored text")

    if not parser.parse_args().log_file:
        parser.print_help()
        exit(1)

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    filter_groups = load_filters(args.filter)
    line_counter = [0]

    ram_samples = []
    stop_event = threading.Event()
    sampler = threading.Thread(target=_sample_ram, args=(
        ram_samples, stop_event), daemon=True)
    sampler.start()

    matches = list(analyze_log(args.log_file, filter_groups,
                   args.criticality, line_counter))

    stop_event.set()
    sampler.join()

    if args.json:
        json_output(matches, ram_samples, stats=args.s,
                    lines_scanned=line_counter[0])
    else:
        user_output(matches, ram_samples, filter_groups,
                    stats=args.s, lines_scanned=line_counter[0])
