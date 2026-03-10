import pytest
from analyze import Filter, FilterGroup, analyze_log


def test_matching_line_yielded(log_file, sample_groups):
    path = log_file(["kernel panic detected"])
    counter = [0]
    results = list(analyze_log(path, sample_groups, "high", counter))
    assert len(results) == 1
    assert results[0] == (1, "kernel panic", "high", "kernel panic detected")


def test_non_matching_line_skipped(log_file, sample_groups):
    path = log_file(["everything is fine"])
    counter = [0]
    results = list(analyze_log(path, sample_groups, "high", counter))
    assert results == []


def test_line_counter_reflects_total_lines(log_file, sample_groups):
    path = log_file(["line one", "line two", "line three"])
    counter = [0]
    list(analyze_log(path, sample_groups, "high", counter))
    assert counter[0] == 3


def test_line_counter_with_no_matches(log_file, sample_groups):
    path = log_file(["nothing", "to", "match"])
    counter = [0]
    list(analyze_log(path, sample_groups, "high", counter))
    assert counter[0] == 3


def test_empty_file_yields_nothing(log_file, sample_groups):
    path = log_file([])
    counter = [0]
    results = list(analyze_log(path, sample_groups, "high", counter))
    assert results == []
    assert counter[0] == 0


def test_line_numbers_are_correct(log_file, sample_groups):
    path = log_file(["nothing here", "kernel panic occurred", "also nothing"])
    counter = [0]
    results = list(analyze_log(path, sample_groups, "high", counter))
    assert results[0][0] == 2  # line 2


def test_multiple_matches_across_lines(log_file, sample_groups):
    path = log_file(["kernel panic first", "fine", "kernel panic again"])
    counter = [0]
    results = list(analyze_log(path, sample_groups, "high", counter))
    assert len(results) == 2
    assert results[0][0] == 1
    assert results[1][0] == 3


def test_criticality_threshold_excludes_higher_severity(log_file, sample_groups):
    # "kernel panic" has criticality="high" (enum value=1)
    # threshold="medium" (enum value=2): 1 >= 2 is False → not yielded
    path = log_file(["kernel panic occurred"])
    counter = [0]
    results = list(analyze_log(path, sample_groups, "medium", counter))
    assert results == []


def test_criticality_threshold_includes_matching_severity(log_file, sample_groups):
    # "blocking process" has criticality="medium" (enum value=2)
    # threshold="medium" (enum value=2): 2 >= 2 is True → yielded
    path = log_file(["task blocked for more than 30 seconds"])
    counter = [0]
    results = list(analyze_log(path, sample_groups, "medium", counter))
    assert len(results) == 1
    assert results[0][1] == "blocking process"


def test_each_group_matched_independently_per_line(log_file):
    # The break exits the inner filter loop (one filter match per group),
    # but all groups are still evaluated — each matching group yields separately.
    groups = [
        FilterGroup("first", "high", [Filter("error", False, False, False)]),
        FilterGroup("second", "high", [Filter("error", False, False, False)]),
    ]
    path = log_file(["an error occurred"])
    counter = [0]
    results = list(analyze_log(path, groups, "high", counter))
    assert len(results) == 2
    assert results[0][1] == "first"
    assert results[1][1] == "second"


def test_regex_filter_matches(log_file):
    groups = [FilterGroup("oom", "high",
                          [Filter(r"Out of memory: Kill process \d+", True, False, False)])]
    path = log_file(["Out of memory: Kill process 1234"])
    counter = [0]
    results = list(analyze_log(path, groups, "high", counter))
    assert len(results) == 1


def test_file_not_found_raises(sample_groups):
    with pytest.raises(FileNotFoundError):
        list(analyze_log("nonexistent.log", sample_groups, "high", [0]))
