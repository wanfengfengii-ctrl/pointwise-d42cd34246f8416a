import re
from dataclasses import dataclass
from fractions import Fraction


_TIME_TEXT = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]+)?|[0-9]+/[0-9]+)')


def parse_shift_second(value: object) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if type(value) is int:
        return Fraction(value)
    if isinstance(value, str) and _TIME_TEXT.fullmatch(value):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError(f'invalid shift second {value!r}') from exc
    raise ValueError(f'expected an exact shift second, got {value!r}')


def encode_shift_second(value: object) -> str:
    return str(parse_shift_second(value))


@dataclass(frozen=True, init=False)
class ClosedWindow:
    start: Fraction
    end: Fraction

    def __init__(self, start: object, end: object) -> None:
        lower = parse_shift_second(start)
        upper = parse_shift_second(end)
        if lower > upper:
            raise ValueError('closed window starts after it ends')
        object.__setattr__(self, 'start', lower)
        object.__setattr__(self, 'end', upper)

    def intersection(self, other: 'ClosedWindow') -> 'ClosedWindow | None':
        lower = max(self.start, other.start)
        upper = min(self.end, other.end)
        if lower > upper:
            return None
        return ClosedWindow(lower, upper)

    def contains(self, value: object) -> bool:
        return self.start <= parse_shift_second(value) <= self.end

    def shift(self, amount: object) -> 'ClosedWindow':
        delta = parse_shift_second(amount)
        return ClosedWindow(self.start + delta, self.end + delta)

    def to_document(self) -> list[str]:
        return [encode_shift_second(self.start), encode_shift_second(self.end)]

    @classmethod
    def from_document(cls, document: object) -> 'ClosedWindow':
        if not isinstance(document, list) or len(document) != 2:
            raise ValueError('a closed window needs two endpoints')
        return cls(document[0], document[1])
