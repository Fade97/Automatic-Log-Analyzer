import json
import re
import pytest
from analyze import Filter, FilterGroup, json_output, user_output


def strip_ansi(text):
    return re.sub(r"\033\[[0-9;]*m", "", text)


# ---------------------------------------------------------------------------
# json_output
# ---------------------------------------------------------------------------

class TestJsonOutput:
    def test_top_level_keys(self, capsys):
        json_output([], [])
        data = json.loads(capsys.readouterr().out)
        assert "filters" in data
        assert "matches" in data

    def test_each_filter_name_appears_once(self, capsys):
        matches = [
            (1, "kernel panic", "high", "panic line one"),
            (2, "kernel panic", "high", "panic line two"),
            (3, "blocking process", "medium", "task blocked"),
        ]
        json_output(matches, [])
        data = json.loads(capsys.readouterr().out)
        names = [f["name"] for f in data["filters"]]
        assert names.count("kernel panic") == 1
        assert names.count("blocking process") == 1

    def test_match_count(self, capsys):
        matches = [
            (1, "kernel panic", "high", "a"),
            (2, "kernel panic", "high", "b"),
            (3, "blocking process", "medium", "c"),
        ]
        json_output(matches, [])
        data = json.loads(capsys.readouterr().out)
        assert len(data["matches"]) == 3

    def test_filter_ids_reference_filters(self, capsys):
        matches = [
            (1, "group_a", "high", "line one"),
            (2, "group_b", "medium", "line two"),
            (3, "group_a", "high", "line three"),
        ]
        json_output(matches, [])
        data = json.loads(capsys.readouterr().out)
        id_by_name = {f["name"]: f["id"] for f in data["filters"]}
        assert data["matches"][0]["filter_id"] == id_by_name["group_a"]
        assert data["matches"][1]["filter_id"] == id_by_name["group_b"]
        assert data["matches"][2]["filter_id"] == id_by_name["group_a"]

    def test_empty_matches(self, capsys):
        json_output([], [])
        data = json.loads(capsys.readouterr().out)
        assert data["filters"] == []
        assert data["matches"] == []

    def test_stats_block_added_when_requested(self, capsys):
        matches = [(1, "kernel panic", "high", "panic")]
        json_output(matches, [], stats=True, lines_scanned=100)
        data = json.loads(capsys.readouterr().out)
        assert "stats" in data
        assert data["stats"]["lines_scanned"] == 100
        assert data["stats"]["total_matches"] == 1

    def test_no_stats_block_by_default(self, capsys):
        json_output([(1, "kernel panic", "high", "panic")], [])
        data = json.loads(capsys.readouterr().out)
        assert "stats" not in data

    def test_ram_stats_included(self, capsys):
        matches = [(1, "kernel panic", "high", "panic")]
        ram = [1024, 2048, 3072]  # bytes
        json_output(matches, ram, stats=True, lines_scanned=10)
        data = json.loads(capsys.readouterr().out)
        assert "stats" in data
        assert "ram_usage" in data["stats"]
        assert data["stats"]["ram_usage"]["unit"] == "kb"
        assert data["stats"]["ram_usage"]["min"] == pytest.approx(1.0)
        assert data["stats"]["ram_usage"]["max"] == pytest.approx(3.0)
        assert data["stats"]["lines_scanned"] == 10
        assert data["stats"]["total_matches"] == 1


# ---------------------------------------------------------------------------
# user_output
# ---------------------------------------------------------------------------

class TestUserOutput:
    def _groups(self):
        return [FilterGroup("kernel panic", "high",
                            [Filter("kernel panic", False, False, False)])]

    def test_match_is_printed(self, capsys):
        matches = [(42, "kernel panic", "high", "Kernel panic occurred")]
        user_output(matches, [], self._groups())
        out = strip_ansi(capsys.readouterr().out)
        assert "42" in out
        assert "kernel panic" in out
        assert "Kernel panic occurred" in out
        assert "HIGH" in out

    def test_empty_matches_no_output_no_crash(self, capsys):
        user_output([], [], self._groups())
        assert capsys.readouterr().out == ""

    def test_stats_block_printed_when_requested(self, capsys):
        matches = [(1, "kernel panic", "high", "panic")]
        user_output(matches, [], self._groups(), stats=True, lines_scanned=50)
        out = strip_ansi(capsys.readouterr().out)
        assert "Stats" in out
        assert "50" in out

    def test_no_stats_block_by_default(self, capsys):
        matches = [(1, "kernel panic", "high", "panic")]
        user_output(matches, [], self._groups())
        out = strip_ansi(capsys.readouterr().out)
        assert "Stats" not in out

    def test_ram_stats_printed(self, capsys):
        matches = [(1, "kernel panic", "high", "panic")]
        ram = [1024, 2048, 3072]
        user_output(matches, ram, self._groups(), stats=True, lines_scanned=10)
        out = strip_ansi(capsys.readouterr().out)
        assert "RAM" in out

    def test_line_numbers_are_padded_consistently(self, capsys):
        groups = [FilterGroup("g", "high", [Filter("x", False, False, False)])]
        matches = [(1, "g", "high", "x"), (100, "g", "high", "x")]
        user_output(matches, [], groups)
        out = strip_ansi(capsys.readouterr().out)
        lines = [l for l in out.splitlines() if l.strip()]
        # The opening bracket [ should be at the same column in both lines
        assert lines[0].index("[") == lines[1].index("[")
