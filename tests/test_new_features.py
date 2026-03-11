"""Tests for features added in the second feature round:
match highlighting, --fail-on, stdin support, context lines (-C),
multiple files, negation filters, AND logic, compressed files,
deduplication (--dedupe), watch mode, --max-matches, --validate-filter.
"""
import gzip
import bz2
import json
import re
import sys
import pytest

from analyze import (
    Filter, FilterGroup,
    analyze_log, load_filters,
    _deduplicate, _find_match_span, _apply_highlight,
    _group_matches,
    json_output, user_output,
    parse_arguments,
    COLORS,
)


def strip_ansi(text):
    return re.sub(r"\033\[[0-9;]*m", "", text)


# ---------------------------------------------------------------------------
# Helper fixtures / builders
# ---------------------------------------------------------------------------

def _group(name="g", crit="high", pattern="error", regex=False, logic="or", negate=False):
    return FilterGroup(name, crit, [Filter(pattern, regex, False, False, negate=negate)], logic=logic)


# ---------------------------------------------------------------------------
# 1. Match highlighting
# ---------------------------------------------------------------------------

class TestMatchHighlighting:
    def test_find_match_span_returns_correct_offsets(self):
        group = _group(pattern="panic")
        span = _find_match_span("kernel panic happened", group)
        assert span == (7, 12)

    def test_find_match_span_none_when_no_match(self):
        group = _group(pattern="oom")
        assert _find_match_span("everything is fine", group) is None

    def test_apply_highlight_wraps_span(self):
        result = _apply_highlight("kernel panic", (7, 12))
        assert result == f"kernel {COLORS['bold']}panic{COLORS['reset']}"

    def test_apply_highlight_none_span_returns_unchanged(self):
        line = "no match here"
        assert _apply_highlight(line, None) is line

    def test_user_output_contains_bold_code(self, capsys):
        group = FilterGroup("panic", "high", [Filter("panic", False, False, False)])
        matches = [(1, "panic", "high", "kernel panic")]
        user_output(matches, [], [group])
        out = capsys.readouterr().out
        assert COLORS["bold"] in out

    def test_user_output_text_preserved_after_strip(self, capsys):
        group = FilterGroup("panic", "high", [Filter("panic", False, False, False)])
        matches = [(1, "panic", "high", "kernel panic")]
        user_output(matches, [], [group])
        out = strip_ansi(capsys.readouterr().out)
        assert "kernel panic" in out


# ---------------------------------------------------------------------------
# 2. Negation filters
# ---------------------------------------------------------------------------

class TestNegationFilters:
    def test_negated_filter_matches_line_without_pattern(self):
        f = Filter("DEBUG", False, False, False, negate=True)
        assert f.match("INFO something happened") is True

    def test_negated_filter_does_not_match_line_with_pattern(self):
        f = Filter("DEBUG", False, False, False, negate=True)
        assert f.match("DEBUG verbose noise") is False

    def test_negated_find_returns_none(self):
        f = Filter("error", False, False, False, negate=True)
        assert f.find("error found") is None

    def test_negated_filter_in_analyze_log(self, log_file):
        # Group matches lines that do NOT contain "DEBUG"
        group = FilterGroup("non-debug", "high",
                            [Filter("DEBUG", False, False, False, negate=True)])
        path = log_file(["DEBUG verbose", "INFO important", "DEBUG noise"])
        counter = [0]
        results = list(analyze_log(path, [group], "high", counter))
        assert len(results) == 1
        assert results[0][3] == "INFO important"

    def test_load_filters_with_negate(self, tmp_path):
        data = [{"name": "g", "criticality": "high", "filters": [
            {"filter": "DEBUG", "regex": False, "case_sensitive": False,
             "word_match": False, "negate": True}
        ]}]
        p = tmp_path / "f.json"
        p.write_text(json.dumps(data))
        groups = load_filters(str(p))
        assert groups[0].filters[0].negate is True


# ---------------------------------------------------------------------------
# 3. AND logic in filter groups
# ---------------------------------------------------------------------------

class TestAndLogic:
    def test_and_logic_requires_all_filters(self):
        group = FilterGroup("both", "high", [
            Filter("error", False, False, False),
            Filter("disk", False, False, False),
        ], logic="and")
        assert _group_matches(group, "disk error occurred") is True
        assert _group_matches(group, "error only") is False
        assert _group_matches(group, "disk only") is False

    def test_or_logic_any_filter_sufficient(self):
        group = FilterGroup("either", "high", [
            Filter("error", False, False, False),
            Filter("disk", False, False, False),
        ], logic="or")
        assert _group_matches(group, "error only") is True
        assert _group_matches(group, "disk only") is True

    def test_and_logic_in_analyze_log(self, log_file):
        group = FilterGroup("disk-error", "high", [
            Filter("error", False, False, False),
            Filter("disk", False, False, False),
        ], logic="and")
        path = log_file(["disk error critical", "error only", "disk only"])
        counter = [0]
        results = list(analyze_log(path, [group], "high", counter))
        assert len(results) == 1
        assert results[0][3] == "disk error critical"

    def test_load_filters_with_logic(self, tmp_path):
        data = [{"name": "g", "criticality": "high", "logic": "and", "filters": [
            {"filter": "a", "regex": False, "case_sensitive": False, "word_match": False},
            {"filter": "b", "regex": False, "case_sensitive": False, "word_match": False},
        ]}]
        p = tmp_path / "f.json"
        p.write_text(json.dumps(data))
        groups = load_filters(str(p))
        assert groups[0].logic == "and"

    def test_filter_group_default_logic_is_or(self):
        group = FilterGroup("g", "high", [])
        assert group.logic == "or"


# ---------------------------------------------------------------------------
# 4. Context lines (-C N)
# ---------------------------------------------------------------------------

class TestContextLines:
    def test_pre_context_lines_yielded(self, log_file):
        group = _group(pattern="match")
        path = log_file(["before", "match line", "after"])
        counter = [0]
        results = list(analyze_log(path, [group], "high", counter, context=1))
        # Should include context line before and after the match
        line_nums = [r[0] for r in results]
        assert 1 in line_nums   # "before" as pre-context
        assert 2 in line_nums   # "match line"
        assert 3 in line_nums   # "after" as post-context

    def test_context_line_has_none_group_and_criticality(self, log_file):
        group = _group(pattern="match")
        path = log_file(["before", "match line"])
        counter = [0]
        results = list(analyze_log(path, [group], "high", counter, context=1))
        context_entries = [r for r in results if r[1] is None]
        assert len(context_entries) == 1
        assert context_entries[0][2] is None  # criticality also None
        assert context_entries[0][3] == "before"

    def test_no_context_when_zero(self, log_file):
        group = _group(pattern="match")
        path = log_file(["before", "match line", "after"])
        counter = [0]
        results = list(analyze_log(path, [group], "high", counter, context=0))
        assert len(results) == 1
        assert results[0][1] == "g"

    def test_context_lines_not_duplicated_when_overlapping(self, log_file):
        group = _group(pattern="match")
        path = log_file(["match1", "shared", "match2"])
        counter = [0]
        results = list(analyze_log(path, [group], "high", counter, context=1))
        # "shared" (line 2) would be post-context of match1 AND pre-context of match2
        shared_entries = [r for r in results if r[3] == "shared"]
        assert len(shared_entries) == 1

    def test_context_lines_shown_dim_in_user_output(self, capsys):
        group = _group(pattern="match")
        matches = [(1, None, None, "context text"), (2, "g", "high", "match text")]
        groups = [FilterGroup("g", "high", [Filter("match", False, False, False)])]
        user_output(matches, [], groups)
        out = capsys.readouterr().out
        assert COLORS["dim"] in out
        assert "context text" in out

    def test_context_lines_have_double_dash_marker_in_user_output(self, capsys):
        matches = [(1, None, None, "ctx"), (2, "g", "high", "hit")]
        groups = [FilterGroup("g", "high", [Filter("hit", False, False, False)])]
        user_output(matches, [], groups)
        out = strip_ansi(capsys.readouterr().out)
        assert "--" in out

    def test_context_lines_excluded_from_json_filter_map(self, capsys):
        matches = [(1, None, None, "ctx"), (2, "panic", "high", "hit")]
        json_output(matches, [])
        data = json.loads(capsys.readouterr().out)
        # Only "panic" should appear in filters, not context
        assert len(data["filters"]) == 1
        assert data["filters"][0]["name"] == "panic"

    def test_context_entries_have_type_context_in_json(self, capsys):
        matches = [(1, None, None, "ctx line"), (2, "g", "high", "match")]
        json_output(matches, [])
        data = json.loads(capsys.readouterr().out)
        ctx_entries = [m for m in data["matches"] if m.get("type") == "context"]
        assert len(ctx_entries) == 1
        assert ctx_entries[0]["text"] == "ctx line"


# ---------------------------------------------------------------------------
# 5. Max matches (--max-matches)
# ---------------------------------------------------------------------------

class TestMaxMatches:
    def test_stops_after_max_matches(self, log_file):
        group = _group(pattern="error")
        path = log_file(["error 1", "error 2", "error 3", "error 4"])
        counter = [0]
        results = list(analyze_log(path, [group], "high", counter, max_matches=2))
        assert len(results) == 2

    def test_unlimited_by_default(self, log_file):
        group = _group(pattern="error")
        path = log_file(["error 1", "error 2", "error 3"])
        counter = [0]
        results = list(analyze_log(path, [group], "high", counter))
        assert len(results) == 3


# ---------------------------------------------------------------------------
# 6. Compressed file support
# ---------------------------------------------------------------------------

class TestCompressedFiles:
    def test_gz_file_readable(self, tmp_path):
        gz_path = str(tmp_path / "test.log.gz")
        with gzip.open(gz_path, "wt") as f:
            f.write("kernel panic here\n")
            f.write("everything fine\n")
        group = _group(pattern="panic")
        counter = [0]
        results = list(analyze_log(gz_path, [group], "high", counter))
        assert len(results) == 1
        assert "panic" in results[0][3]

    def test_bz2_file_readable(self, tmp_path):
        bz2_path = str(tmp_path / "test.log.bz2")
        with bz2.open(bz2_path, "wt") as f:
            f.write("kernel panic here\n")
            f.write("everything fine\n")
        group = _group(pattern="panic")
        counter = [0]
        results = list(analyze_log(bz2_path, [group], "high", counter))
        assert len(results) == 1

    def test_gz_line_counter_correct(self, tmp_path):
        gz_path = str(tmp_path / "test.log.gz")
        with gzip.open(gz_path, "wt") as f:
            f.write("line one\nline two\nline three\n")
        group = _group(pattern="nomatch")
        counter = [0]
        list(analyze_log(gz_path, [group], "high", counter))
        assert counter[0] == 3


# ---------------------------------------------------------------------------
# 7. Stdin support ('-')
# ---------------------------------------------------------------------------

class TestStdinSupport:
    def test_stdin_reads_lines(self, monkeypatch):
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO("kernel panic\nall fine\n"))
        group = _group(pattern="panic")
        counter = [0]
        results = list(analyze_log("-", [group], "high", counter))
        assert len(results) == 1
        assert results[0][3] == "kernel panic"

    def test_stdin_line_counter(self, monkeypatch):
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO("a\nb\nc\n"))
        group = _group(pattern="nomatch")
        counter = [0]
        list(analyze_log("-", [group], "high", counter))
        assert counter[0] == 3


# ---------------------------------------------------------------------------
# 8. Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_consecutive_identical_matches_collapsed(self):
        matches = [
            (1, "panic", "high", "kernel panic"),
            (2, "panic", "high", "kernel panic"),
            (3, "panic", "high", "kernel panic"),
        ]
        result = _deduplicate(matches)
        assert len(result) == 1
        assert "(x3)" in result[0][3]

    def test_non_consecutive_not_collapsed(self):
        matches = [
            (1, "panic", "high", "kernel panic"),
            (2, "oom", "high", "out of memory"),
            (3, "panic", "high", "kernel panic"),
        ]
        result = _deduplicate(matches)
        assert len(result) == 3

    def test_different_groups_not_collapsed(self):
        matches = [
            (1, "panic", "high", "same text"),
            (2, "oom", "high", "same text"),
        ]
        result = _deduplicate(matches)
        assert len(result) == 2

    def test_context_lines_break_chain(self):
        matches = [
            (1, "panic", "high", "kernel panic"),
            (2, None, None, "context line"),
            (3, "panic", "high", "kernel panic"),
        ]
        result = _deduplicate(matches)
        assert len(result) == 3

    def test_empty_list(self):
        assert _deduplicate([]) == []

    def test_single_match_unchanged(self):
        matches = [(1, "panic", "high", "kernel panic")]
        result = _deduplicate(matches)
        assert result == matches

    def test_count_suffix_format(self):
        matches = [(1, "g", "high", "text"), (2, "g", "high", "text")]
        result = _deduplicate(matches)
        assert result[0][3] == "text (x2)"


# ---------------------------------------------------------------------------
# 9. --validate-filter (parse_arguments integration)
# ---------------------------------------------------------------------------

class TestValidateFilter:
    def test_validate_filter_does_not_require_log_file(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["analyze.py", "--validate-filter", "filter.json"])
        args = parse_arguments()
        assert args.validate_filter == "filter.json"
        assert args.log_files == []

    def test_no_log_no_validate_exits(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["analyze.py"])
        with pytest.raises(SystemExit):
            parse_arguments()


# ---------------------------------------------------------------------------
# 10. --fail-on / new argument defaults
# ---------------------------------------------------------------------------

class TestNewArguments:
    def test_fail_on_default_is_none(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["analyze.py", "test.log"])
        args = parse_arguments()
        assert args.fail_on is None

    def test_fail_on_set(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["analyze.py", "test.log", "--fail-on", "high"])
        args = parse_arguments()
        assert args.fail_on == "high"

    def test_context_default_is_zero(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["analyze.py", "test.log"])
        args = parse_arguments()
        assert args.context == 0

    def test_context_set(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["analyze.py", "test.log", "-C", "3"])
        args = parse_arguments()
        assert args.context == 3

    def test_watch_default_false(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["analyze.py", "test.log"])
        args = parse_arguments()
        assert args.watch is False

    def test_dedupe_default_false(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["analyze.py", "test.log"])
        args = parse_arguments()
        assert args.dedupe is False

    def test_max_matches_default_none(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["analyze.py", "test.log"])
        args = parse_arguments()
        assert args.max_matches is None

    def test_max_matches_set(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["analyze.py", "test.log", "--max-matches", "10"])
        args = parse_arguments()
        assert args.max_matches == 10

    def test_multiple_log_files(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["analyze.py", "a.log", "b.log"])
        args = parse_arguments()
        assert args.log_files == ["a.log", "b.log"]


# ---------------------------------------------------------------------------
# 11. Multiple files in output
# ---------------------------------------------------------------------------

class TestMultipleFilesOutput:
    def test_user_output_filename_header(self, capsys):
        groups = [FilterGroup("g", "high", [Filter("x", False, False, False)])]
        matches = [(1, "g", "high", "x")]
        user_output(matches, [], groups, filename="syslog")
        out = strip_ansi(capsys.readouterr().out)
        assert "==> syslog <==" in out

    def test_user_output_no_header_by_default(self, capsys):
        groups = [FilterGroup("g", "high", [Filter("x", False, False, False)])]
        matches = [(1, "g", "high", "x")]
        user_output(matches, [], groups)
        out = strip_ansi(capsys.readouterr().out)
        assert "==>" not in out

    def test_json_output_filename_in_matches(self, capsys):
        matches = [(1, "g", "high", "x")]
        json_output(matches, [], filename="syslog")
        data = json.loads(capsys.readouterr().out)
        assert data["matches"][0]["file"] == "syslog"

    def test_json_output_no_file_field_by_default(self, capsys):
        matches = [(1, "g", "high", "x")]
        json_output(matches, [])
        data = json.loads(capsys.readouterr().out)
        assert "file" not in data["matches"][0]
