"""Match formatting helpers: deduplication and highlight."""
from analyze.models import COLORS


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
