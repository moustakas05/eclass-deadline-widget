from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from scraper import parse_assignments, parse_date

ATHENS = ZoneInfo("Europe/Athens")


def test_greek_month_date_is_timezone_aware():
    result = parse_date("15 Μαΐου 2027 13:45")
    assert result == datetime(2027, 5, 15, 13, 45, tzinfo=ATHENS)


def test_numeric_date_without_time_defaults_to_end_of_day():
    result = parse_date("15-05-2027")
    assert result == datetime(2027, 5, 15, 23, 59, tzinfo=ATHENS)


def test_invalid_calendar_date_is_ignored():
    assert parse_date("31-02-2027") is None


def test_assignment_parser_extracts_deadline_and_absolute_link():
    html = '''<table><tr><th>Assignment</th><th>Deadline</th><th>Submitted</th></tr>
    <tr><td><a href="/modules/work/view.php?id=42">Essay</a></td>
    <td>15-05-2027 12:30</td><td>No</td></tr></table>'''
    rows = parse_assignments(BeautifulSoup(html, "html.parser"),
                             "https://eclass.uowm.gr/modules/work/")
    assert len(rows) == 1
    assert rows[0]["title"] == "Essay"
    assert rows[0]["deadline"] == "2027-05-15T12:30+03:00"
    assert rows[0]["url"] == "https://eclass.uowm.gr/modules/work/view.php?id=42"
    assert rows[0]["submitted"] is False


def test_empty_course_table_returns_no_deadlines():
    soup = BeautifulSoup("<table><tr><th>Assignment</th><th>Deadline</th></tr></table>",
                         "html.parser")
    assert parse_assignments(soup, "https://eclass.uowm.gr/") == []
