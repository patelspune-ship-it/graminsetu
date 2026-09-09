from fractions import Fraction

from app.fin.core import round_half_up


def indian_currency(value: int | None) -> str:
    """Format integer paise without float conversion or loss of paise."""
    if value is None:
        return "Not established"

    if type(value) is not int:
        raise TypeError("Currency values must be integer paise")

    negative = value < 0
    rupees, paise = divmod(abs(value), 100)
    digits = str(rupees)

    if len(digits) > 3:
        tail = digits[-3:]
        head = digits[:-3]
        groups = []

        while head:
            groups.append(head[-2:])
            head = head[:-2]

        digits = ",".join(reversed(groups)) + "," + tail

    suffix = f".{paise:02d}" if paise else ""
    return f"{'-' if negative else ''}₹{digits}{suffix}"


def bps_percent(value: int) -> str:
    if type(value) is not int:
        raise TypeError("Rates must be integer basis points")

    sign = "-" if value < 0 else ""
    whole, fraction = divmod(abs(value), 100)
    return f"{sign}{whole}.{fraction:02d}%"


def fraction_ratio(value: Fraction | None) -> str:
    if value is None:
        return "N/A — no debt service"

    if not isinstance(value, Fraction):
        raise TypeError("Ratio must be Fraction or None")

    scaled = round_half_up(abs(value) * 100)
    whole, fraction = divmod(scaled, 100)
    return f"{'-' if value < 0 else ''}{whole}.{fraction:02d}"


def known(value: object) -> str:
    return "Not established" if value is None else str(value)