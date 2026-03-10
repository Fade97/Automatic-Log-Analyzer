import pytest
from analyze import parse_arguments


def test_no_log_file_exits(monkeypatch):
    monkeypatch.setattr("sys.argv", ["analyze.py"])
    with pytest.raises(SystemExit):
        parse_arguments()


def test_valid_log_file(monkeypatch):
    monkeypatch.setattr("sys.argv", ["analyze.py", "test.log"])
    args = parse_arguments()
    assert args.log_file == "test.log"


def test_default_criticality_is_high(monkeypatch):
    monkeypatch.setattr("sys.argv", ["analyze.py", "test.log"])
    args = parse_arguments()
    assert args.criticality == "HIGH"


def test_criticality_medium(monkeypatch):
    monkeypatch.setattr("sys.argv", ["analyze.py", "test.log", "--criticality", "medium"])
    args = parse_arguments()
    assert args.criticality == "medium"


def test_invalid_criticality_exits(monkeypatch):
    monkeypatch.setattr("sys.argv", ["analyze.py", "test.log", "--criticality", "critical"])
    with pytest.raises(SystemExit):
        parse_arguments()


def test_stats_flag_false_by_default(monkeypatch):
    monkeypatch.setattr("sys.argv", ["analyze.py", "test.log"])
    args = parse_arguments()
    assert args.s is False


def test_stats_flag_enabled(monkeypatch):
    monkeypatch.setattr("sys.argv", ["analyze.py", "test.log", "-s"])
    args = parse_arguments()
    assert args.s is True


def test_json_flag_false_by_default(monkeypatch):
    monkeypatch.setattr("sys.argv", ["analyze.py", "test.log"])
    args = parse_arguments()
    assert args.json is False


def test_json_flag_enabled(monkeypatch):
    monkeypatch.setattr("sys.argv", ["analyze.py", "test.log", "--json"])
    args = parse_arguments()
    assert args.json is True


def test_custom_filter_file(monkeypatch):
    monkeypatch.setattr("sys.argv", ["analyze.py", "test.log", "--filter", "my_filters.json"])
    args = parse_arguments()
    assert args.filter == "my_filters.json"
