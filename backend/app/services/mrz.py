"""ICAO 9303 TD3 Machine-Readable-Zone (MRZ) parser for passports.

A passport's bio page carries a two-line, 44-character MRZ printed in a
fixed Latin/ASCII font (letters, digits, `<` filler) with embedded check
digits — the same format regardless of the page's printed language. This
module locates that zone in already-transcribed `raw_text` (see
`extraction.py::_file_to_text`), validates its check digits, and returns a
language-independent, checksum-verified read of the fields it encodes.

Fails open throughout: `extract_mrz_fields` returns `{}` if no MRZ is found
or its composite check digit doesn't validate, rather than raising — a
missing/garbled MRZ (cropped photo, an OCR engine mangling the dense `<`
text, etc.) should never break extraction, just skip this overlay.

Note: TD3 only checksums four fields on line 2 (passport number, date of
birth, date of expiry, personal number) plus one composite digit covering
those four. Line 1's name field has no check digit of its own — its
accuracy rests on the composite check having validated line 2, not on any
direct verification of line 1.
"""
import re
from datetime import date

_LINE_RE = re.compile(r"^[A-Z0-9<]{44}$")

_CHECK_VALUES = {str(d): d for d in range(10)}
_CHECK_VALUES.update({chr(ord("A") + i): 10 + i for i in range(26)})
_CHECK_VALUES["<"] = 0

_WEIGHTS = (7, 3, 1)


def _check_digit(data: str) -> int:
    return sum(_CHECK_VALUES.get(c, 0) * _WEIGHTS[i % 3] for i, c in enumerate(data)) % 10


def _valid_check(data: str, check_char: str) -> bool | None:
    """None means "not applicable" — an unused optional field, check slot is `<`."""
    if check_char == "<":
        return None
    if not check_char.isdigit():
        return False
    return _check_digit(data) == int(check_char)


def _candidate_lines(raw_text: str) -> list[str]:
    candidates = []
    for line in raw_text.splitlines():
        normalized = re.sub(r"\s+", "", line.strip().upper())
        if _LINE_RE.match(normalized):
            candidates.append(normalized)
    return candidates


def _resolve_dob_year(yy: int, today: date) -> int | None:
    """A birth date can't be in the future; prefer the more recent century
    among the two that fit, per ICAO convention."""
    for year in (2000 + yy, 1900 + yy):
        if year > today.year:
            continue
        if 0 <= today.year - year <= 120:
            return year
    return None


def _resolve_expiry_year(yy: int, today: date) -> int:
    """Passports are valid ~10 years, so the century numerically closer to
    today is overwhelmingly likely to be correct."""
    return min((2000 + yy, 1900 + yy), key=lambda year: abs(year - today.year))


def _parse_date(yy_mm_dd: str, today: date, *, is_dob: bool) -> date | None:
    yy, mm, dd = int(yy_mm_dd[0:2]), int(yy_mm_dd[2:4]), int(yy_mm_dd[4:6])
    year = _resolve_dob_year(yy, today) if is_dob else _resolve_expiry_year(yy, today)
    if year is None:
        return None
    try:
        return date(year, mm, dd)
    except ValueError:
        return None


def _parse_name_field(field: str) -> tuple[str, str]:
    surname, _, given = field.partition("<<")
    return surname.replace("<", " ").strip(), re.sub(r"<+", " ", given).strip()


def _try_parse_pair(line1: str, line2: str, today: date) -> dict:
    if line1[0] != "P":
        return {}

    passport_number = line2[0:9]
    dob_raw = line2[13:19]
    expiry_raw = line2[21:27]
    personal_number = line2[28:42]

    composite_data = line2[0:10] + line2[13:20] + line2[21:28] + line2[28:43]
    if not _valid_check(composite_data, line2[43]):
        return {}

    surname, given_names = _parse_name_field(line1[5:44])
    sex_char = line2[20]
    dob = _parse_date(dob_raw, today, is_dob=True)
    expiry = _parse_date(expiry_raw, today, is_dob=False)
    personal_number_clean = personal_number.rstrip("<") or None

    return {
        "mrz_document_type": line1[0],
        "mrz_issuing_country": line1[2:5].rstrip("<"),
        "mrz_surname": surname,
        "mrz_given_names": given_names,
        "mrz_passport_number": passport_number.rstrip("<"),
        "mrz_passport_number_valid": bool(_valid_check(passport_number, line2[9])),
        "mrz_nationality": line2[10:13].rstrip("<"),
        "mrz_date_of_birth": dob.isoformat() if dob else None,
        "mrz_date_of_birth_valid": bool(_valid_check(dob_raw, line2[19])),
        "mrz_sex": sex_char if sex_char in ("M", "F") else "X",
        "mrz_date_of_expiry": expiry.isoformat() if expiry else None,
        "mrz_date_of_expiry_valid": bool(_valid_check(expiry_raw, line2[27])),
        "mrz_personal_number": personal_number_clean,
        "mrz_personal_number_valid": _valid_check(personal_number, line2[42]),
        "mrz_composite_valid": True,
    }


def extract_mrz_fields(raw_text: str, today: date | None = None) -> dict:
    """Locate, parse, and checksum-validate a TD3 MRZ within `raw_text`.

    Returns a dict of `mrz_*` fields if a composite-valid MRZ pair is
    found, else `{}`. `today` is exposed only so callers/tests can pin
    "now" for century inference; defaults to `date.today()`.
    """
    today = today or date.today()
    candidates = _candidate_lines(raw_text)
    for i in range(len(candidates) - 1):
        result = _try_parse_pair(candidates[i], candidates[i + 1], today)
        if result:
            return result
    return {}
