"""JSON output formatting."""
import json
from collections import Counter


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
