"""Core log analysis: file opening and line-by-line matching."""
import bz2
import gzip
import sys
from collections import deque
from time import sleep

from analyze.models import enum_criticality


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
