import argparse
import json
import re
from collections import namedtuple, Counter
from enum import Enum
import threading
from time import sleep
import tracemalloc

COLORS = {
    "reset": "\033[0m",
    "high": "\033[31m",
    "medium": "\033[33m",
    "low": "\033[37m"
}

enum_criticality = Enum("Criticality", ["HIGH", "MEDIUM", "LOW"])

filters_file = "filter.json"

FilterGroup = namedtuple("FilterGroup", ["name", "criticality", "filters"])


def _sample_ram(samples, stop_event, interval=0.01):
    tracemalloc.start()
    while not stop_event.is_set():
        current, _ = tracemalloc.get_traced_memory()
        samples.append(current)
        sleep(interval)
    tracemalloc.stop()


class Filter:
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
    with open(filters_file, "r") as f:
        data = json.load(f)
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


# Parse arguments
# --log: Log file
# --filter: Filters file
# usage: python analyze.py <log_file> --filter <filters_file>
# if no log file is provided, print the help message


def parse_arguments():
    parser = argparse.ArgumentParser(description="Analyze logs")
    parser.add_argument("log_file", type=str, help="Log file",
                        nargs="?")
    parser.add_argument("--filter", type=str,
                        default=filters_file, help="Filters file")
    parser.add_argument("--criticality", type=str,
                        default="HIGH", help="Criticality", choices=[e.name.lower() for e in enum_criticality])
    parser.add_argument("-s", action="store_true",
                        help="Print stats after analysis")
    parser.add_argument("--json",
                        action="store_true", help="Output the data as json")

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
        json_output(matches, ram_samples, stats=args.s, lines_scanned=line_counter[0])
    else:
        user_output(matches, ram_samples, filter_groups, stats=args.s, lines_scanned=line_counter[0])
