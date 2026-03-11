"""
Automatic Log Analyzer

Streams a log file line-by-line and reports lines that match configurable
filter groups. Supports plain substring matching and regular expressions,
with optional case sensitivity and word-boundary constraints.

Usage:
    python analyze.py <log_file> [options]
    python analyze.py --validate-filter filter.json
"""
import argparse
import bz2
import gzip
import json
import re
import sys
from collections import namedtuple, Counter, deque
from enum import Enum
import threading
from time import sleep
import tracemalloc

import jsonschema

COLORS = {
    "reset": "\033[0m",
    "high": "\033[31m",
    "medium": "\033[33m",
    "low": "\033[37m",
    "bold": "\033[1m",
    "dim": "\033[2m",
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
            "logic": {"type": "string", "enum": ["or", "and"]},
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
                        "word_match": {"type": "boolean"},
                        "negate": {"type": "boolean"},
                    }
                }
            }
        }
    }
}

filters_file = "filter.json"


class FilterGroup(namedtuple("FilterGroup", ["name", "criticality", "filters", "logic"])):
    """Named tuple representing a filter group with an optional logic field."""

    def __new__(cls, name, criticality, filters, logic="or"):
        return super().__new__(cls, name, criticality, filters, logic)


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
        negate (bool): If True, match lines that do NOT contain the pattern.
    """

    def __init__(self, filter, regex, case_sensitive, word_match, negate=False):
        self.filter = filter
        self.regex = regex
        self.case_sensitive = case_sensitive
        self.word_match = word_match
        self.negate = negate

    def _build_pattern(self):
        flags = 0 if self.case_sensitive else re.IGNORECASE
        if self.regex:
            pat = rf"\b{self.filter}\b" if self.word_match else self.filter
        else:
            pat = rf"\b{re.escape(self.filter)}\b" if self.word_match else re.escape(
                self.filter)
        return pat, flags

    def match(self, log_line):
        pat, flags = self._build_pattern()
        result = bool(re.search(pat, log_line, flags))
        return not result if self.negate else result

    def find(self, log_line):
        """Return the re.Match for the first hit, or None. Always None for negated filters."""
        if self.negate:
            return None
        pat, flags = self._build_pattern()
        return re.search(pat, log_line, flags)


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
            Filter(f["filter"], f["regex"], f["case_sensitive"], f["word_match"],
                   negate=f.get("negate", False))
            for f in group["filters"]
        ]
        groups.append(FilterGroup(
            group["name"], group["criticality"], filter_objs,
            logic=group.get("logic", "or")
        ))
    return groups


def _open_log(path):
    """Open a log file for reading, supporting stdin, .gz, and .bz2.

    Args:
        path (str): File path, '-' for stdin, or a path ending in .gz/.bz2.

    Returns:
        A file-like object opened in text mode.
    """
    if path == "-":
        return sys.stdin
    if path.endswith(".gz"):
        return gzip.open(path, "rt", errors="replace")
    if path.endswith(".bz2"):
        return bz2.open(path, "rt", errors="replace")
    return open(path, "r", errors="replace")


def _group_matches(group, line):
    """Return True if `line` satisfies the group's filter logic (OR or AND)."""
    combine = all if group.logic == "and" else any
    return combine(filt.match(line) for filt in group.filters)


def analyze_log(log_file, filter_groups, criticality, line_counter,
                context=0, max_matches=None, watch=False):
    """Stream a log file and yield lines that match any filter group.

    Reads the file one line at a time, keeping memory usage constant
    regardless of file size. Supports pre/post context lines, match
    limits, and tail/watch mode.

    Args:
        log_file (str): Path to the log file, or '-' for stdin.
        filter_groups (list[FilterGroup]): Filter groups to apply.
        criticality (str): Minimum criticality level to report
            ('high', 'medium', or 'low').
        line_counter (list[int]): Single-element list updated with the
            current line number as the file is read.
        context (int): Lines of context to show before and after each match.
            Default 0.
        max_matches (int|None): Stop after this many total matches.
            Default None (unlimited).
        watch (bool): If True, tail the file for new lines after EOF.
            Default False. Has no effect when reading stdin.

    Yields:
        tuple[int, str|None, str|None, str]:
            (line_number, group_name, criticality, line_text)
            group_name and criticality are None for context lines.

    Raises:
        FileNotFoundError: If the log file does not exist.
    """
    threshold = enum_criticality[criticality.upper()].value
    pre_buf = deque(maxlen=context) if context > 0 else None
    post_remaining = 0
    emitted_ctx = set()  # line numbers emitted as context (prevents duplicates)
    match_count = 0

    def _process_line(line_num, line):
        nonlocal post_remaining, match_count
        entries = []
        found_match = False

        for group in filter_groups:
            if _group_matches(group, line):
                if enum_criticality[group.criticality.upper()].value >= threshold:
                    found_match = True
                    # Emit buffered pre-context lines not yet shown
                    if pre_buf is not None:
                        for ctx_num, ctx_line in pre_buf:
                            if ctx_num not in emitted_ctx:
                                emitted_ctx.add(ctx_num)
                                entries.append((ctx_num, None, None, ctx_line))
                    emitted_ctx.add(line_num)
                    entries.append(
                        (line_num, group.name, group.criticality, line))
                    post_remaining = max(post_remaining, context)
                    match_count += 1
                    if max_matches is not None and match_count >= max_matches:
                        return entries, True

        if not found_match:
            if post_remaining > 0:
                if line_num not in emitted_ctx:
                    emitted_ctx.add(line_num)
                    entries.append((line_num, None, None, line))
                post_remaining -= 1
            if pre_buf is not None and line_num not in emitted_ctx:
                pre_buf.append((line_num, line))

        return entries, False

    with _open_log(log_file) as f:
        for raw in f:
            line_counter[0] += 1
            line = raw.rstrip("\n")
            entries, stop = _process_line(line_counter[0], line)
            yield from entries
            if stop:
                return

        if watch and log_file != "-":
            while True:
                try:
                    raw = f.readline()
                    if raw:
                        line_counter[0] += 1
                        line = raw.rstrip("\n")
                        if line == "":
                            continue
                        entries, stop = _process_line(line_counter[0], line)
                        yield from entries
                        if stop:
                            return
                    else:
                        sleep(0.1)
                except KeyboardInterrupt:
                    return


def _deduplicate(matches):
    """Collapse consecutive identical match lines from the same group into one.

    Context lines (group_name is None) break the consecutive chain.

    Args:
        matches (list[tuple]): List of (line_num, group_name, criticality, text) tuples.

    Returns:
        list[tuple]: Deduplicated list; repeated lines get ' (xN)' appended to their text.
    """
    if not matches:
        return []
    result = []
    prev = matches[0]
    count = 1
    for match in matches[1:]:
        if (match[1] is not None and prev[1] is not None
                and match[1] == prev[1] and match[3] == prev[3]):
            count += 1
        else:
            if count > 1:
                ln, name, crit, line = prev
                result.append((ln, name, crit, f"{line} (x{count})"))
            else:
                result.append(prev)
            prev = match
            count = 1
    if count > 1:
        ln, name, crit, line = prev
        result.append((ln, name, crit, f"{line} (x{count})"))
    else:
        result.append(prev)
    return result


def _find_match_span(line, group):
    """Return (start, end) of the first filter match span in line, or None."""
    for filt in group.filters:
        m = filt.find(line)
        if m:
            return m.start(), m.end()
    return None


def _apply_highlight(line, span):
    """Wrap the matched span with bold ANSI codes. Returns line unchanged if span is None."""
    if span is None:
        return line
    start, end = span
    return line[:start] + COLORS["bold"] + line[start:end] + COLORS["reset"] + line[end:]


def _stream_text_output(gen, filter_groups, stats=False, line_counter=None,
                        fail_on=None, dedupe=False, filename=None):
    """Stream matches from a generator to stdout immediately, one line at a time.

    Args:
        gen: Generator yielding (line_num, group_name, criticality, text) tuples.
            group_name and criticality are None for context lines.
        filter_groups (list[FilterGroup]): Used for name widths and highlighting.
        stats (bool): If True, print a stats block after the generator is exhausted.
        line_counter (list[int]): Single-element list holding the current line count
            (updated live by the generator); used in the stats block.
        fail_on (str|None): Criticality level string; if any match meets or exceeds
            this level, the function returns True.
        dedupe (bool): If True, collapse consecutive identical matches with a count.
        filename (str|None): When set, print a '==> filename <==' header first.

    Returns:
        bool: True if any match triggered the --fail-on threshold.
    """
    name_to_group = {g.name: g for g in filter_groups}
    name_width = max((len(g.name) for g in filter_groups), default=0)
    crit_width = max(len(e.name) for e in enum_criticality)
    fail_threshold = enum_criticality[fail_on.upper()].value if fail_on else None
    fail_triggered = False
    match_counts = Counter()

    prev_match = None  # (line_num, name, criticality, line) — held for dedupe
    prev_count = 0

    def _emit(line_num, name, criticality, line, count=1):
        nonlocal fail_triggered
        match_counts[(name, criticality)] += count
        if fail_threshold is not None:
            if enum_criticality[criticality.upper()].value >= fail_threshold:
                fail_triggered = True
        group = name_to_group.get(name)
        display = _apply_highlight(line, _find_match_span(line, group)) if group else line
        if count > 1:
            display = f"{display} (x{count})"
        color = COLORS.get(criticality.lower(), "")
        crit_text = f"{color}{criticality.upper():{crit_width}}{COLORS['reset']}"
        print(f"{COLORS['low']}l{line_num}{COLORS['reset']} "
              f"[{crit_text}] ({name:{name_width}}): {display}", flush=True)

    def _flush_prev():
        nonlocal prev_match, prev_count
        if prev_match is not None:
            _emit(*prev_match, count=prev_count)
            prev_match = None
            prev_count = 0

    if filename is not None:
        print(f"==> {filename} <==", flush=True)

    try:
        for line_num, name, criticality, line in gen:
            if name is None:
                _flush_prev()
                print(f"{COLORS['dim']}  l{line_num}-- {line}{COLORS['reset']}", flush=True)
            elif dedupe:
                if (prev_match is not None
                        and prev_match[1] == name and prev_match[3] == line):
                    prev_count += 1
                else:
                    _flush_prev()
                    prev_match = (line_num, name, criticality, line)
                    prev_count = 1
            else:
                _emit(line_num, name, criticality, line)
    except KeyboardInterrupt:
        pass

    _flush_prev()

    if stats:
        total_matches = sum(match_counts.values())
        lines = line_counter[0] if line_counter is not None else 0
        print(f"\n--- Stats ---")
        print(f"Lines scanned : {lines}")
        print(f"Total matches : {total_matches}")
        for (name, crit), count in match_counts.items():
            color = COLORS.get(crit.lower(), "")
            print(f"  {color}{crit.upper():{crit_width}}{COLORS['reset']} "
                  f"({name:{name_width}}): {count}")

    return fail_triggered


def _build_json_output(matches, ram_samples, stats=False, lines_scanned=0, filename=None):
    """Build and return the JSON output dict (without printing).

    Args:
        matches (list[tuple]): List of (line_num, name, criticality, line) tuples.
            name and criticality are None for context lines.
        ram_samples (list[int]): Memory samples in bytes from _sample_ram.
        stats (bool): If True, include a stats block.
        lines_scanned (int): Total lines read from the log file.
        filename (str|None): When set, adds a "file" field to each match entry.

    Returns:
        dict: JSON-serialisable output document.
    """
    filter_map = {}  # name -> {id, criticality}
    match_counts = Counter()

    for _, name, criticality, _ in matches:
        if name is None:
            continue  # context line
        if name not in filter_map:
            filter_map[name] = {
                "id": len(filter_map), "criticality": criticality}
        match_counts[filter_map[name]["id"]] += 1

    match_entries = []
    for line_num, name, _, line in matches:
        entry = {"line_number": line_num, "text": line}
        if filename is not None:
            entry["file"] = filename
        if name is None:
            entry["type"] = "context"
        else:
            entry["filter_id"] = filter_map[name]["id"]
        match_entries.append(entry)

    doc = {
        "filters": [{"id": d["id"], "name": n, "criticality": d["criticality"]}
                    for n, d in filter_map.items()],
        "matches": match_entries,
    }

    if stats:
        total_matches = sum(match_counts.values())
        doc["stats"] = {
            "lines_scanned": lines_scanned,
            "total_matches": total_matches,
            "filter_matches": [
                {"id": mid, "count": cnt} for mid, cnt in match_counts.items()
            ],
        }
        if ram_samples:
            ram_samples = ram_samples[1:] if ram_samples[0] == 0 else ram_samples
            to_kb = 1 / 1024
            doc["stats"]["ram_usage"] = {
                "min": min(ram_samples) * to_kb,
                "avg": sum(ram_samples) / len(ram_samples) * to_kb,
                "max": max(ram_samples) * to_kb,
                "unit": "kb",
            }

    return doc


def json_output(matches, ram_samples, stats=False, lines_scanned=0, filename=None):
    """Print analysis results as a JSON document.

    Each filter name appears once in "filters"; matches reference filters
    by integer ID. Context lines are included with type "context".
    Optionally includes a "stats" block.

    Args:
        matches (list[tuple]): List of (line_num, name, criticality, line) tuples.
            name and criticality are None for context lines.
        ram_samples (list[int]): Memory samples in bytes from _sample_ram.
        stats (bool): If True, include a stats block in the output.
        lines_scanned (int): Total lines read from the log file.
        filename (str|None): When set, adds a "file" field to each match entry.
    """
    print(json.dumps(_build_json_output(matches, ram_samples, stats, lines_scanned, filename),
                     indent=2))


def user_output(matches, ram_samples, filter_groups, stats=False, lines_scanned=0,
                filename=None):
    """Print analysis results as aligned, color-coded text.

    Column widths are derived from the widest values in the result set so
    all columns line up regardless of data. Context lines are printed in dim
    with no metadata. Matched substrings are highlighted in bold.

    Args:
        matches (list[tuple]): List of (line_num, name, criticality, line) tuples.
            name and criticality are None for context lines.
        ram_samples (list[int]): Memory samples in bytes from _sample_ram.
        filter_groups (list[FilterGroup]): Loaded filter groups (used to
            compute the maximum filter name width and for highlighting).
        stats (bool): If True, print a stats summary after the matches.
        lines_scanned (int): Total lines read from the log file.
        filename (str|None): When set, print a '==> filename <==' header.
    """
    name_to_group = {g.name: g for g in filter_groups}
    name_width = max((len(g.name) for g in filter_groups), default=0)
    crit_width = max(len(e.name) for e in enum_criticality)

    match_entries = [(ln, n, c, l) for ln, n, c, l in matches if n is not None]
    line_num_width = len(str(match_entries[-1][0])) if match_entries else 1

    match_counts = Counter()

    if filename is not None:
        print(f"==> {filename} <==")

    for line_num, name, criticality, line in matches:
        if name is None:
            # Context line: dim, no criticality/group metadata
            print(
                f"{COLORS['dim']}  l{line_num:{line_num_width}}-- {line}{COLORS['reset']}")
            continue

        match_counts[(name, criticality)] += 1
        group = name_to_group.get(name)
        if group is not None:
            display_line = _apply_highlight(
                line, _find_match_span(line, group))
        else:
            display_line = line

        color = COLORS.get(criticality.lower(), "")
        criticality_text = f"{color}{criticality.upper():{crit_width}}{COLORS['reset']}"
        print(
            f"{COLORS['low']}l{line_num:{line_num_width}}{COLORS['reset']} "
            f"[{criticality_text}] ({name:{name_width}}): {display_line}")

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

    Prints help and exits with code 1 if no log file is provided (and
    --validate-filter is not used). Argparse enforces valid choices for
    --criticality, --fail-on.

    Returns:
        argparse.Namespace: Parsed arguments with attributes:
            log_files (list[str]), filter (str), criticality (str), s (bool),
            json (bool), context (int), watch (bool), dedupe (bool),
            max_matches (int|None), fail_on (str|None),
            validate_filter (str|None).
    """
    parser = argparse.ArgumentParser(description="Analyze logs")
    parser.add_argument("log_files", type=str,
                        help="Path(s) to log file(s) to analyze (use '-' for stdin)",
                        nargs="*")
    parser.add_argument("--filter", type=str,
                        default=filters_file,
                        help="Path to filter configuration JSON file (default: filter.json)")
    parser.add_argument("--criticality", type=str,
                        default="LOW",
                        help="Minimum criticality level to report: high, medium, or low (default: high)",
                        choices=[e.name.lower() for e in enum_criticality])
    parser.add_argument("-s", action="store_true",
                        help="Print a stats summary after analysis (line count, match count, RAM usage)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON instead of colored text")
    parser.add_argument("-C", "--context", type=int, default=0, metavar="N",
                        help="Show N lines of context before and after each match")
    parser.add_argument("--watch", action="store_true",
                        help="Tail the file and report new matches as lines are appended")
    parser.add_argument("--dedupe", action="store_true",
                        help="Collapse consecutive identical matches into one with a count")
    parser.add_argument("--max-matches", type=int, default=None, metavar="N",
                        help="Stop after N total matches")
    parser.add_argument("--fail-on", type=str, default=None, metavar="LEVEL",
                        choices=[e.name.lower() for e in enum_criticality],
                        help="Exit with code 1 if any match at or above LEVEL is found")
    parser.add_argument("--validate-filter", type=str, default=None, metavar="FILE",
                        help="Validate a filter JSON file and exit (no log file needed)")

    parsed = parser.parse_args()
    if parsed.validate_filter is None and not parsed.log_files:
        parser.print_help()
        exit(1)

    return parsed


if __name__ == "__main__":
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
