"""Bikram Sambat date parsing: issue titles, legacy-font mastheads, ad deadlines."""
import datetime
import re

import nepali_datetime

DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
MONTHS = {
    1: "बैशाख वैशाख बैसाख", 2: "जेठ जेष्ठ ज्येष्ठ", 3: "असार आषाढ", 4: "साउन श्रावण",
    5: "भदौ भदाै भाद्र", 6: "असोज आश्विन असोझ", 7: "कात्तिक कार्तिक",
    8: "मंसिर मङ्सिर मङ्गसिर मंगसिर", 9: "पुस पौष पौस", 10: "माघ",
    11: "फागुन फाल्गुन फाल्गुण", 12: "चैत्र चैत",
}
MONTH_OF = {name: num for num, names in MONTHS.items() for name in names.split()}
_M = "(" + "|".join(sorted(MONTH_OF, key=len, reverse=True)) + ")"
_DAY_FIRST = re.compile(r"(\d{1,2})\s*" + _M + r"\s*,?\s*(\d{4})")
_MONTH_FIRST = re.compile(_M + r"\s*(\d{1,2})\s*,?\s*(\d{4})")

# Legacy (Preeti-style) fonts type digits as shifted number-row symbols.
PREETI_DIGITS = str.maketrans("!@#$%^&*()", "1234567890")
# Every masthead month spelling seen across the 4,372 archive PDFs (2013–2026),
# each checked against the issue titles' month.
PREETI_MONTHS = {
    "j}zfv": 1, "a}zfv": 1, "j+}zfv": 1,
    "h]7": 2, "h]i7": 2, "Ho]i7": 2,
    "c;f/": 3, "cfiff9": 3,
    ";fpg": 4,
    "ebf}": 5, "efb|": 5,
    "c;f]h": 6,
    "sflQs": 7, "sflt{s": 7,
    "d+l;/": 8, "dª\\l;/": 8, "dlª\\;/": 8,
    "k';": 9, "k'if": 9,
    "df3": 10,
    "kmfu'g": 11,
    "r}t": 12, "r}q": 12,
}
_MASTHEAD = re.compile(r"([!@#$%^&*()]{4})\s+(\S+)\s+([!@#$%^&*()]{1,2})\s+ut\]")
_YMD = re.compile(r"(20\d\d)\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{1,2})")
_MONTH_DAY = re.compile(_M + r"\s*(\d{1,2})\s*गते")
_RELATIVE = re.compile(r"(\d{1,3})\s*(?:दिन|days?)", re.I)


def bs_date(y, m, d):
    try:
        return nepali_datetime.date(y, m, d)
    except (ValueError, KeyError, IndexError, OverflowError):
        return None


def parse_bs_iso(text):
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", (text or "").strip())
    return bs_date(*map(int, m.groups())) if m else None


def parse_title(title):
    t = title.translate(DEV_DIGITS)
    if m := _DAY_FIRST.search(t):
        day, month, year = m.groups()
    elif m := _MONTH_FIRST.search(t):
        month, day, year = m.groups()
    else:
        return None
    return bs_date(int(year), MONTH_OF[month], int(day))


def parse_masthead(text):
    """Only the first date on page 1 is the masthead; later ones are dates inside articles."""
    m = _MASTHEAD.search(text)
    month = PREETI_MONTHS.get(m.group(2)) if m else None
    if not month:
        return None
    return bs_date(int(m.group(1).translate(PREETI_DIGITS)), month, int(m.group(3).translate(PREETI_DIGITS)))


def resolve_issue_date(masthead, title, post_ad):
    """Pick the issue date: masthead, else title if it agrees with the post date, else post date.

    Returns (bs_date, source, conflict)."""
    post_bs = nepali_datetime.date.from_datetime_date(post_ad)

    def near(a, b):
        return abs((a.to_datetime_date() - b.to_datetime_date()).days) <= 2

    if masthead:
        return masthead, "masthead", not all(near(masthead, x) for x in (title, post_bs) if x)
    if title and near(title, post_bs):
        return title, "title", False
    return post_bs, "post", title is not None


ROMAN_MONTHS = {
    "baisakh": 1, "baishakh": 1, "baishak": 1, "jestha": 2, "jeth": 2, "ashar": 3, "asar": 3, "asadh": 3,
    "shrawan": 4, "sharwan": 4, "saun": 4, "bhadra": 5, "bhadau": 5, "ashoj": 6, "asoj": 6, "ashwin": 6,
    "kartik": 7, "mangsir": 8, "mansir": 8, "poush": 9, "paush": 9, "push": 9, "magh": 10,
    "falgun": 11, "fagun": 11, "phalgun": 11, "chaitra": 12, "chait": 12,
}
AD_MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                          "august", "september", "october", "november", "december"], 1)}
_RM = "(" + "|".join(sorted(ROMAN_MONTHS, key=len, reverse=True)) + ")"
_AM = "(" + "|".join(AD_MONTHS) + ")"
_ORD = r"(\d{1,2})(?:st|nd|rd|th)?"
_ROMAN_DAY_FIRST = re.compile(_ORD + r"\s*(?:of\s+)?" + _RM + r"\b,?\s*(\d{4})?", re.I)
_ROMAN_MONTH_FIRST = re.compile(_RM + r"\s+" + _ORD + r"\b,?\s*(\d{4})?", re.I)
_AD_DAY_FIRST = re.compile(_ORD + r"\s*(?:of\s+)?" + _AM + r",?\s*(\d{4})", re.I)
_WEEKS = re.compile(r"(एक|दुई|तीन|1|2|3)\s*(?:हप्ता|weeks?)", re.I)
_WEEK_N = {"एक": 1, "दुई": 2, "तीन": 3, "1": 1, "2": 2, "3": 3}


def _bs_with_year(issue_bs, month, day, year=None):
    """BS date; a missing year means the next occurrence on or after the issue date."""
    if year:
        return bs_date(int(year), month, day)
    bs = bs_date(issue_bs.year, month, day)
    if bs and bs < issue_bs:
        bs = bs_date(issue_bs.year + 1, month, day)
    return bs


def parse_deadline(text, issue_bs):
    """Deadline text as printed -> (AD date or None, derived_from_relative)."""
    if not text:
        return None, False
    t = text.translate(DEV_DIGITS)
    if m := _AD_DAY_FIRST.search(t):
        try:
            return datetime.date(int(m.group(3)), AD_MONTHS[m.group(2).lower()], int(m.group(1))), False
        except ValueError:
            return None, False
    for pat, day_first in ((_ROMAN_DAY_FIRST, True), (_ROMAN_MONTH_FIRST, False)):
        if m := pat.search(t):
            day, month = (m.group(1), m.group(2)) if day_first else (m.group(2), m.group(1))
            bs = _bs_with_year(issue_bs, ROMAN_MONTHS[month.lower()], int(day), m.group(3))
            return (bs.to_datetime_date() if bs else None), False
    if m := _WEEKS.search(t):
        return issue_bs.to_datetime_date() + datetime.timedelta(days=7 * _WEEK_N[m.group(1)]), True
    if m := _YMD.search(t):
        y, mo, d = map(int, m.groups())
        if y > 2060:
            bs = bs_date(y, mo, d)
            return (bs.to_datetime_date() if bs else None), False
        try:
            return datetime.date(y, mo, d), False
        except ValueError:
            return None, False
    if bs := parse_title(t):
        return bs.to_datetime_date(), False
    if m := _MONTH_DAY.search(t):
        month, day = MONTH_OF[m.group(1)], int(m.group(2))
        bs = bs_date(issue_bs.year, month, day)
        if bs and bs < issue_bs:
            bs = bs_date(issue_bs.year + 1, month, day)
        return (bs.to_datetime_date() if bs else None), False
    if m := _RELATIVE.search(t):
        return issue_bs.to_datetime_date() + datetime.timedelta(days=int(m.group(1))), True
    return None, False
