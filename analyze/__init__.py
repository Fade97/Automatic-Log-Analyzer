"""Automatic Log Analyzer package.

Re-exports all public symbols so that ``from analyze import X`` works
for both application code and tests.
"""
from analyze.analysis import analyze_log, _group_matches
from analyze.args import parse_arguments
from analyze.filters import load_filters
from analyze.formatting import _apply_highlight, _deduplicate, _find_match_span
from analyze.json_output import json_output
from analyze.models import COLORS, Filter, FilterGroup, enum_criticality
from analyze.output import _stream_text_output, user_output

__all__ = [
    "COLORS",
    "Filter",
    "FilterGroup",
    "enum_criticality",
    "load_filters",
    "analyze_log",
    "_group_matches",
    "_deduplicate",
    "_find_match_span",
    "_apply_highlight",
    "_stream_text_output",
    "user_output",
    "json_output",
    "parse_arguments",
]
