"""Text output: streaming and buffered."""
from collections import Counter

from analyze.formatting import _apply_highlight, _find_match_span
from analyze.models import COLORS, enum_criticality


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
