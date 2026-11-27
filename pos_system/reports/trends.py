"""
Analytics › Trends tab: the last few complete weeks, months or quarters.

Two views of the same periods:
* two figures side by side over time ("Sold units & sales"), drawn as two
  small charts on one time axis rather than one chart with two scales;
* one figure against the same period a year earlier ("Year over year").

Figures and words are the Performance tab's (performance.METRICS): Sales is
what was rung up, before refunds. Only complete periods are shown, so a
half-finished week never looks like a bad one. Archived sales are included.
"""
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta

from .performance import Totals, _at_midnight, _lines, _months_later

CADENCES = {'weekly': 'Weekly', 'monthly': 'Monthly', 'quarterly': 'Quarterly'}
DEFAULT_CADENCE = 'weekly'
COUNT = {'weekly': 8, 'monthly': 6, 'quarterly': 4}     # periods on the charts
PLURAL = {'weekly': 'weeks', 'monthly': 'months', 'quarterly': 'quarters'}


@dataclass
class Period:
    label: str            # axis label: 'Wk 47', 'Oct', 'Q3'
    long_label: str       # tooltip / table: 'Wk 47 · Nov 16 – 22, 2026'
    start: date           # inclusive
    end: date             # exclusive
    ly_start: date = None  # the same period a year earlier (None: no such period)
    ly_end: date = None


def _span(start, last):
    """'Nov 16 – 22, 2026' / 'Dec 28, 2026 – Jan 3, 2027'."""
    if start.year != last.year:
        return f'{start:%b} {start.day}, {start.year} – {last:%b} {last.day}, {last.year}'
    if start.month != last.month:
        return f'{start:%b} {start.day} – {last:%b} {last.day}, {last.year}'
    return f'{start:%b} {start.day} – {last.day}, {last.year}'


def build_periods(cadence, today):
    """The last COUNT complete periods, oldest first, each with its match a year back."""
    n = COUNT[cadence]
    out = []
    if cadence == 'weekly':
        this_monday = today - timedelta(days=today.weekday())
        for k in range(n, 0, -1):
            start = this_monday - timedelta(weeks=k)
            year, week, _ = start.isocalendar()
            p = Period(f'Wk {week}', f'Wk {week} · {_span(start, start + timedelta(days=6))}',
                       start, start + timedelta(days=7))
            try:   # the same ISO week last year (a 53rd week may not exist)
                p.ly_start = date.fromisocalendar(year - 1, week, 1)
                p.ly_end = p.ly_start + timedelta(days=7)
            except ValueError:
                pass
            out.append(p)
        return out

    months = 1 if cadence == 'monthly' else 3
    first = today.replace(day=1)
    if months == 3:
        first = first.replace(month=(first.month - 1) // 3 * 3 + 1)
    for k in range(n, 0, -1):
        start = _months_later(first, -months * k)
        end = _months_later(start, months)
        if months == 1:
            label, long_label = f'{start:%b}', f'{start:%B %Y}'
        else:
            q = (start.month - 1) // 3 + 1
            label, long_label = f'Q{q} {start.year}', f'Q{q} {start.year} · {_span(start, end - timedelta(days=1))}'
        out.append(Period(label, long_label, start, end,
                          start.replace(year=start.year - 1), end.replace(year=end.year - 1)))
    return out


def _bucket(lines, starts, ends):
    """Totals per period for lines falling in [starts[i], ends[i])."""
    totals = [Totals() for _ in starts]
    for when, qty, price in lines:
        day = when.date()
        i = bisect_right(starts, day) - 1
        if 0 <= i < len(starts) and day < ends[i]:
            totals[i].add(qty, price)
    return totals


def collect(cadence, now):
    """Totals per period and for the same periods a year earlier."""
    from django.utils import timezone

    cadence = cadence if cadence in CADENCES else DEFAULT_CADENCE
    today = timezone.localtime(now).date()
    periods = build_periods(cadence, today)

    lines, ok_now = _lines(_at_midnight(periods[0].start), _at_midnight(periods[-1].end))
    lines = [(timezone.localtime(w), q, p) for w, q, p in lines]
    current = _bucket(lines, [p.start for p in periods], [p.end for p in periods])

    have = [p for p in periods if p.ly_start]
    last_year = [None] * len(periods)
    ok_ly = True
    if have:
        ly_lines, ok_ly = _lines(_at_midnight(have[0].ly_start), _at_midnight(have[-1].ly_end))
        ly_lines = [(timezone.localtime(w), q, p) for w, q, p in ly_lines]
        ly = _bucket(ly_lines, [p.ly_start for p in have], [p.ly_end for p in have])
        for p, t in zip(have, ly):
            last_year[periods.index(p)] = t

    return {
        'cadence': cadence,
        'periods': periods,
        'current': current,
        'last_year': last_year,
        'archive_ok': ok_now and ok_ly,
    }
