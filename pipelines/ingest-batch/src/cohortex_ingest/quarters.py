"""Quarter labels (`YYYYQn`) and their calendar ranges (implementation-notes §3)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

_LABEL = re.compile(r"^(\d{4})Q([1-4])$")


@dataclass(frozen=True, order=True)
class Quarter:
    year: int
    q: int

    @classmethod
    def parse(cls, label: str) -> Quarter:
        m = _LABEL.match(label.strip().upper())
        if not m:
            raise ValueError(f"invalid quarter {label!r}; expected YYYYQn, e.g. 2026Q2")
        return cls(int(m.group(1)), int(m.group(2)))

    @classmethod
    def of(cls, day: date) -> Quarter:
        return cls(day.year, (day.month - 1) // 3 + 1)

    @property
    def label(self) -> str:
        return f"{self.year}Q{self.q}"

    @property
    def start(self) -> date:
        return date(self.year, 3 * self.q - 2, 1)

    @property
    def end(self) -> date:
        return self.next().start - timedelta(days=1)

    def next(self) -> Quarter:
        return Quarter(self.year + 1, 1) if self.q == 4 else Quarter(self.year, self.q + 1)

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def days(self) -> list[date]:
        n = (self.end - self.start).days + 1
        return [self.start + timedelta(days=i) for i in range(n)]

    @property
    def zip_name(self) -> str:
        return f"data_Q{self.q}_{self.year}.zip"

    def __str__(self) -> str:
        return self.label


def month_starts(start: date, end: date) -> list[date]:
    """First day of every month that overlaps ``[start, end]``."""
    out: list[date] = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        out.append(cur)
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return out
