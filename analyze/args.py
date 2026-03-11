"""Command-line argument parsing."""
import argparse
import sys

from analyze.filters import filters_file
from analyze.models import enum_criticality


def parse_arguments():
    """Parse and validate command-line arguments.

    Prints help and exits with code 1 if no log file is provided (and
    --validate-filter is not used). Argparse enforces valid choices for
    --criticality, --fail-on.

    Returns:
        argparse.Namespace: Parsed arguments with attributes:
            log_files (list[str]), filter (str), criticality (str), s (bool),
            json (bool), context (int), watch (bool), dedupe (bool),
            max_matches (int|None), fail_on (str|None),
            validate_filter (str|None).
    """
    parser = argparse.ArgumentParser(description="Analyze logs")
    parser.add_argument("log_files", type=str,
                        help="Path(s) to log file(s) to analyze (use '-' for stdin)",
                        nargs="*")
    parser.add_argument("--filter", type=str,
                        default=filters_file,
                        help="Path to filter configuration JSON file (default: filter.json)")
    parser.add_argument("--criticality", type=str,
                        default="LOW",
                        help="Minimum criticality level to report: high, medium, or low (default: high)",
                        choices=[e.name.lower() for e in enum_criticality])
    parser.add_argument("-s", action="store_true",
                        help="Print a stats summary after analysis (line count, match count, RAM usage)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON instead of colored text")
    parser.add_argument("-C", "--context", type=int, default=0, metavar="N",
                        help="Show N lines of context before and after each match")
    parser.add_argument("--watch", action="store_true",
                        help="Tail the file and report new matches as lines are appended")
    parser.add_argument("--dedupe", action="store_true",
                        help="Collapse consecutive identical matches into one with a count")
    parser.add_argument("--max-matches", type=int, default=None, metavar="N",
                        help="Stop after N total matches")
    parser.add_argument("--fail-on", type=str, default=None, metavar="LEVEL",
                        choices=[e.name.lower() for e in enum_criticality],
                        help="Exit with code 1 if any match at or above LEVEL is found")
    parser.add_argument("--validate-filter", type=str, default=None, metavar="FILE",
                        help="Validate a filter JSON file and exit (no log file needed)")

    parsed = parser.parse_args()
    if parsed.validate_filter is None and not parsed.log_files:
        parser.print_help()
        sys.exit(1)

    return parsed
