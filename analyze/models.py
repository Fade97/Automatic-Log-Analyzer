"""Data models and constants for the log analyzer."""
import re
from collections import namedtuple
from enum import Enum

COLORS = {
    "reset": "\033[0m",
    "high": "\033[31m",
    "medium": "\033[33m",
    "low": "\033[37m",
    "bold": "\033[1m",
    "dim": "\033[2m",
}

enum_criticality = Enum("Criticality", ["LOW", "MEDIUM", "HIGH"])


class FilterGroup(namedtuple("FilterGroup", ["name", "criticality", "filters", "logic"])):
    """Named tuple representing a filter group with an optional logic field."""

    def __new__(cls, name, criticality, filters, logic="or"):
        return super().__new__(cls, name, criticality, filters, logic)


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
