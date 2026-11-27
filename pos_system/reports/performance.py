"""
Analytics page: real-time sales performance.

Five figures for a period (units sold, order items, sales and two averages), each compared with the prior period *up to the same point*: at
7:40 PM, "Today" is compared with yesterday until 7:40 PM, not all of
yesterday. A line chart plots one figure for the period against the prior
period, the same day last week (single-day periods) and the same period last
year.

Same words as the Dashboard: "Sales" is what was rung up, before refunds
(completed sales, including ones refunded later; see ledger.SOLD_STATUSES),
and an "order item" is one product line on a receipt. Archived sales are
included.
"""
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import DatabaseError
from django.utils import timezone

from sales.models import SaleItem

from .ledger import SOLD_STATUSES

logger = logging.getLogger(__name__)

PERIODS = {
    'today':     'Today',
    'yesterday': 'Yesterday',
    '7d':        'Last 7 days',
    '15d':       'Last 15 days',
    '30d':       'Last 30 days',
    'week':      'Weekly',
    'month':     'Monthly',
    'quarter':   'Quarterly',
}
DEFAULT_PERIOD = 'today'

# key: (label, kind) — kind decides formatting: 'int', 'money' or 'ratio'
METRICS = {
    'units':          ('Units sold', 'int'),
    'lines':          ('Order items', 'int'),
    'revenue':        ('Sales', 'money'),
    'units_per_line': ('Units / order item', 'ratio'),
    'sales_per_line': ('Sales / order item', 'money'),
}
DEFAULT_METRIC = 'units'

# Colour follows the series' meaning, never its position. Validated as a set
# (all pairs, light surface) with the dataviz palette checker.
SERIES_COLORS = {
    'current':   '#0A5FA8',
    'prior':     '#D2601A',
    'last_week': '#A0367A',
    'last_year': '#2A9D8F',
}


@dataclass
class Series:
    key: str            # 'current', 'prior', 'last_week' or 'last_year'
    label: str          # legend text, e.g. 'Same day last week'
    start: datetime     # aware, inclusive
    end: datetime       # aware, exclusive
    buckets: list = field(default_factory=list)   # [Totals] per x position


@dataclass
class Totals:
    units: int = 0
    lines: int = 0
    revenue: Decimal = Decimal('0.00')

    def add(self, qty, price):
        self.units += qty
        self.lines += 1
        self.revenue += qty * price

    def value(self, metric):
        if metric == 'units':
            return self.units
        if metric == 'lines':
            return self.lines
        if metric == 'revenue':
            return self.revenue
        if not self.lines:
            return None
        if metric == 'units_per_line':
            return Decimal(self.units) / self.lines
        return self.revenue / self.lines    # sales_per_line


# ── Calendar helpers ────────────────────────────────────────────
def _at_midnight(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _years_back(day, years=1):
    try:
        return day.replace(year=day.year - years)
    except ValueError:          # 29 Feb → 28 Feb
        return day.replace(year=day.year - years, day=28)


def _months_later(day, months):
    y, m = divmod(day.month - 1 + months, 12)
    return day.replace(year=day.year + y, month=m + 1, day=1)


def _quarter_start(day):
    return day.replace(month=(day.month - 1) // 3 * 3 + 1, day=1)


# ── Period layout ───────────────────────────────────────────────
def build_series(period, today):
    """(step, [Series]) for a period choice. step is 'hour', 'day' or 'week'.
    The first series is always the current period, the second the prior one
    the figures are compared with."""
    def day_window(first, days):
        return _at_midnight(first), _at_midnight(first + timedelta(days=days))

    def single_day(day, label, prior_label):
        def one(key, lab, d):
            return Series(key, lab, *day_window(d, 1))
        return 'hour', [
            one('current', label, day),
            one('prior', prior_label, day - timedelta(days=1)),
            one('last_week', 'Same day last week', day - timedelta(days=7)),
            one('last_year', 'Same day last year', _years_back(day)),
        ]

    if period == 'yesterday':
        return single_day(today - timedelta(days=1), 'Yesterday', 'Day before')
    if period in ('7d', '15d', '30d'):
        n = int(period[:-1])
        first = today - timedelta(days=n - 1)
        return 'day', [
            Series('current', f'Last {n} days', *day_window(first, n)),
            Series('prior', f'Previous {n} days', *day_window(first - timedelta(days=n), n)),
            Series('last_year', 'Same days last year', *day_window(_years_back(first), n)),
        ]
    if period == 'week':
        monday = today - timedelta(days=today.weekday())
        return 'day', [
            Series('current', 'This week', *day_window(monday, 7)),
            Series('prior', 'Last week', *day_window(monday - timedelta(days=7), 7)),
            # 52 weeks back keeps Monday lined up with Monday
            Series('last_year', 'Same week last year', *day_window(monday - timedelta(weeks=52), 7)),
        ]
    if period in ('month', 'quarter'):
        months = 1 if period == 'month' else 3
        first = today.replace(day=1) if period == 'month' else _quarter_start(today)
        noun = period
        def window(start):
            return _at_midnight(start), _at_midnight(_months_later(start, months))
        return ('day' if period == 'month' else 'week'), [
            Series('current', f'This {noun}', *window(first)),
            Series('prior', f'Last {noun}', *window(_months_later(first, -months))),
            Series('last_year', f'Same {noun} last year', *window(_years_back(first))),
        ]
    return single_day(today, 'Today so far', 'Yesterday')


def bucket_count(step, series):
    if step == 'hour':
        return 24
    longest = max((s.end - s.start).days for s in series)
    return longest if step == 'day' else -(-longest // 7)


def bucket_of(step, series, when):
    """x position of a local datetime within a series."""
    if step == 'hour':
        return when.hour
    days = (when.date() - timezone.localtime(series.start).date()).days
    return days if step == 'day' else days // 7


# ── Data ────────────────────────────────────────────────────────
def _lines(start, end):
    """(created_at, quantity, unit_price) for every line sold in [start, end),
    from the main database and, when reachable, the archive. Returns
    (lines, archive_ok)."""
    rows = list(SaleItem.objects.filter(
        sale__status__in=SOLD_STATUSES, sale__created_at__gte=start, sale__created_at__lt=end,
    ).values_list('sale_id', 'sale__created_at', 'quantity', 'unit_price'))
    try:
        from archive.models import ArchivedSaleItem
        in_main = {r[0] for r in rows}
        rows += [r for r in ArchivedSaleItem.objects.filter(
            sale__status__in=SOLD_STATUSES, sale__created_at__gte=start, sale__created_at__lt=end,
        ).values_list('sale_id', 'sale__created_at', 'quantity', 'unit_price')
            if r[0] not in in_main]      # a run that stopped mid-move
        archive_ok = True
    except DatabaseError:
        logger.exception('Archive database unavailable for the performance tab')
        archive_ok = False
    return [(when, qty, price) for _, when, qty, price in rows], archive_ok


def collect(period, now):
    """Everything the Performance tab shows, for a period choice at `now`."""
    period = period if period in PERIODS else DEFAULT_PERIOD
    now = timezone.localtime(now)
    step, series = build_series(period, now.date())
    n = bucket_count(step, series)

    # How far into the current period we are; the prior period is cut at the
    # same distance from its own start so the comparison is like for like.
    current, prior = series[0], series[1]
    elapsed = min(now, current.end) - current.start
    is_partial = now < current.end
    cut_at = prior.start + elapsed

    so_far, prior_so_far = Totals(), Totals()
    archive_ok = True
    for s in series:
        s.buckets = [Totals() for _ in range(n)]
        lines, ok = _lines(s.start, s.end)
        archive_ok &= ok
        for when, qty, price in lines:
            local = timezone.localtime(when)
            i = bucket_of(step, s, local)
            if 0 <= i < n:
                s.buckets[i].add(qty, price)
            if s is current and when <= now:
                so_far.add(qty, price)
            elif s is prior and when < cut_at:
                prior_so_far.add(qty, price)

    # The current period stops at the bucket we're in; later ones aren't zero,
    # they haven't happened.
    last_bucket = bucket_of(step, current, now) if is_partial else n - 1
    # A shorter period (Feb against Jan) has no positions past its own end.
    lengths = {s.key: (24 if step == 'hour' else bucket_count(step, [s])) for s in series}

    return {
        'period': period,
        'step': step,
        'series': series,
        'n': n,
        'now': now,
        'is_partial': is_partial,
        'cut_at': timezone.localtime(cut_at),
        'last_bucket': last_bucket,
        'lengths': lengths,
        'so_far': so_far,
        'prior_so_far': prior_so_far,
        'archive_ok': archive_ok,
    }


# ── Presentation helpers ────────────────────────────────────────
def delta(curr, prev):
    """(percent, absolute) change, or (None, None) when there's nothing to compare."""
    if curr is None or prev is None:
        return None, None
    diff = curr - prev
    pct = round(float(diff) / float(prev) * 100, 1) if prev else None
    return pct, diff


def bucket_label(period, step, series, i, short=True):
    """x-axis label for position i, named after the current period's dates.
    Months differ in length, so the Monthly chart counts days (1–31)."""
    if step == 'hour':
        h = i % 12 or 12
        return f"{h} {'AM' if i < 12 else 'PM'}" if short else f"{h}:00 {'AM' if i < 12 else 'PM'}"
    if period == 'month':
        return str(i + 1) if short else f"Day {i + 1}"
    start = timezone.localtime(series.start).date()
    day = start + timedelta(days=i if step == 'day' else i * 7)
    if step == 'week':
        return f"{day:%b} {day.day}" if short else f"Week of {day:%b} {day.day}"
    if period == 'week':
        return f"{day:%a} {day.day}" if short else f"{day:%A}, {day:%b} {day.day}"
    return f"{day:%b} {day.day}" if short else f"{day:%a}, {day:%b} {day.day}"


def nice_ceiling(peak, ticks=4):
    """A round top for the y-axis and its step: 0, step, 2·step … ≥ peak."""
    peak = float(peak or 0)
    if peak <= 0:
        return 1.0, 0.25
    raw = peak / ticks
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        step = m * mag
        if step * ticks >= peak:
            return step * ticks, step
    return 10 * mag * ticks, 10 * mag
