import pytest
from analyze import Filter


# Helpers for building filters concisely
def f(pattern, regex=False, case_sensitive=False, word_match=False):
    return Filter(pattern, regex, case_sensitive, word_match)


class TestSubstringMatch:
    def test_basic_match(self):
        assert f("error").match("An error occurred") is True

    def test_no_match(self):
        assert f("panic").match("all good") is False

    def test_case_insensitive_by_default(self):
        assert f("error", case_sensitive=False).match("ERROR occurred") is True

    def test_case_sensitive_miss(self):
        assert f("error", case_sensitive=True).match("ERROR occurred") is False

    def test_case_sensitive_hit(self):
        assert f("error", case_sensitive=True).match("error occurred") is True

    def test_empty_line(self):
        assert f("error").match("") is False

    def test_special_chars_not_treated_as_regex(self):
        # dot in non-regex mode must be escaped — "err.r" should NOT match "error"
        assert f("err.r").match("error") is False

    def test_special_chars_literal_match(self):
        assert f("err.r").match("err.r in the log") is True


class TestWordMatch:
    def test_word_match_hit(self):
        assert f("panic", word_match=True).match("kernel panic here") is True

    def test_word_match_no_partial(self):
        assert f("panic", word_match=True).match("kernelpanic") is False

    def test_word_match_adjacent_punctuation(self):
        # word boundary stops at punctuation
        assert f("panic", word_match=True).match("kernel panic!") is True

    def test_word_match_case_insensitive(self):
        assert f("panic", word_match=True, case_sensitive=False).match("kernel PANIC here") is True

    def test_word_match_case_sensitive_miss(self):
        assert f("panic", word_match=True, case_sensitive=True).match("kernel PANIC here") is False


class TestRegexMatch:
    def test_regex_match(self):
        assert f(r"\d+ errors", regex=True).match("42 errors found") is True

    def test_regex_no_match(self):
        assert f(r"\d+ errors", regex=True).match("no errors") is False

    def test_regex_case_insensitive(self):
        assert f("kernel panic", regex=True, case_sensitive=False).match("KERNEL PANIC") is True

    def test_regex_case_sensitive_miss(self):
        assert f("kernel panic", regex=True, case_sensitive=True).match("KERNEL PANIC") is False

    def test_regex_word_match(self):
        # "err" with word_match should NOT match inside "error"
        assert f("err", regex=True, word_match=True).match("error in log") is False

    def test_regex_word_match_exact(self):
        assert f("err", regex=True, word_match=True).match("an err occurred") is True
