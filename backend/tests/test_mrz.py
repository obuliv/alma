from datetime import date

from app.services.mrz import (
    _candidate_lines,
    _check_digit,
    extract_mrz_fields,
)

# ICAO Doc 9303 Part 4's own worked TD3 example (fictional "Utopia" passport,
# ANNA MARIA ERIKSSON), individual field check digits per the published
# example (passport number -> 6, DOB -> 1, expiry -> 6). Built with .ljust
# and a computed composite digit rather than hand-counted/transcribed
# literals, to avoid a mistyped '<' run or misremembered digit silently
# producing a wrong fixture.
ICAO_LINE1 = ("P<UTO" + "ERIKSSON<<ANNA<MARIA").ljust(44, "<")
_ICAO_PERSONAL_NUMBER = "ZE184226B".ljust(14, "<")
ICAO_LINE2 = (
    "L898902C3" + "6" + "UTO" + "690806" + "1" + "F" + "940623" + "6"
    + _ICAO_PERSONAL_NUMBER + str(_check_digit(_ICAO_PERSONAL_NUMBER))
    + str(
        _check_digit(
            "L898902C3" + "6" + "690806" + "1" + "940623" + "6"
            + _ICAO_PERSONAL_NUMBER + str(_check_digit(_ICAO_PERSONAL_NUMBER))
        )
    )
)

TODAY = date(2026, 7, 10)


def test_lines_are_44_chars():
    assert len(ICAO_LINE1) == 44
    assert len(ICAO_LINE2) == 44


def test_check_digit_known_values():
    # Passport number check digit, per the ICAO worked example.
    assert _check_digit("L898902C3") == 6
    # DOB check digit.
    assert _check_digit("690806") == 1
    # Expiry check digit.
    assert _check_digit("940623") == 6
    # All-filler string checksums to 0.
    assert _check_digit("<<<<<<<<<<") == 0


def test_parse_full_td3_icao_example():
    raw_text = f"Some prose above.\n{ICAO_LINE1}\n{ICAO_LINE2}\nSome prose below."
    result = extract_mrz_fields(raw_text, today=TODAY)

    assert result["mrz_composite_valid"] is True
    assert result["mrz_document_type"] == "P"
    assert result["mrz_issuing_country"] == "UTO"
    assert result["mrz_surname"] == "ERIKSSON"
    assert result["mrz_given_names"] == "ANNA MARIA"
    assert result["mrz_passport_number"] == "L898902C3"
    assert result["mrz_passport_number_valid"] is True
    assert result["mrz_nationality"] == "UTO"
    assert result["mrz_date_of_birth"] == "1969-08-06"
    assert result["mrz_date_of_birth_valid"] is True
    assert result["mrz_sex"] == "F"
    assert result["mrz_date_of_expiry"] == "1994-06-23"
    assert result["mrz_date_of_expiry_valid"] is True
    assert result["mrz_personal_number"] == "ZE184226B"
    assert result["mrz_personal_number_valid"] is True


def test_composite_invalid_returns_empty():
    # Corrupt the composite check digit (last character of line 2).
    corrupted = ICAO_LINE2[:-1] + ("1" if ICAO_LINE2[-1] != "1" else "2")
    raw_text = f"{ICAO_LINE1}\n{corrupted}"
    assert extract_mrz_fields(raw_text, today=TODAY) == {}


def test_no_mrz_lines_present():
    raw_text = "This is a regular G-28 form with no MRZ block at all.\nAttorney: Jane Doe."
    assert extract_mrz_fields(raw_text, today=TODAY) == {}


def test_mrz_embedded_in_noisy_ocr_text():
    raw_text = (
        "PASSPORT\nRepublic of Utopia\n\n"
        "Surname/Prenom: ERIKSSON\nGiven names: ANNA MARIA\n\n"
        f"{ICAO_LINE1}\n{ICAO_LINE2}\n\n"
        "---\n\nForm field values:\nsome_field: true\n"
    )
    result = extract_mrz_fields(raw_text, today=TODAY)
    assert result["mrz_passport_number"] == "L898902C3"


def test_dob_century_inference_recent():
    # yy=05 with today=2024 -> must resolve to 2005, not 1905 (both are
    # numerically "plausible ages" but 2000s is preferred when not future).
    line2 = _build_line2(dob="050101", expiry="300101")
    raw_text = f"{ICAO_LINE1}\n{line2}"
    result = extract_mrz_fields(raw_text, today=date(2024, 1, 1))
    assert result["mrz_date_of_birth"] == "2005-01-01"


def test_dob_century_inference_older():
    # yy=70 with today=2024 -> 2070 would be in the future, so must resolve
    # to 1970.
    line2 = _build_line2(dob="700101", expiry="300101")
    raw_text = f"{ICAO_LINE1}\n{line2}"
    result = extract_mrz_fields(raw_text, today=date(2024, 1, 1))
    assert result["mrz_date_of_birth"] == "1970-01-01"


def test_personal_number_field_unused():
    line2 = _build_line2(personal_number="<" * 14, personal_number_check="<")
    raw_text = f"{ICAO_LINE1}\n{line2}"
    result = extract_mrz_fields(raw_text, today=TODAY)
    assert result["mrz_composite_valid"] is True
    assert result["mrz_personal_number"] is None
    assert result["mrz_personal_number_valid"] is None


def test_candidate_lines_normalizes_whitespace_and_case():
    noisy = " " + ICAO_LINE1.lower() + " "
    assert _candidate_lines(noisy) == [ICAO_LINE1]


def _build_line2(
    *,
    passport_number: str = "L898902C3",
    nationality: str = "UTO",
    dob: str = "690806",
    sex: str = "F",
    expiry: str = "940623",
    personal_number: str = "ZE184226B".ljust(14, "<"),
    personal_number_check: str | None = None,
) -> str:
    """Build a self-consistent TD3 line 2 by computing real check digits via
    `_check_digit`, so synthetic edge-case fixtures don't rely on
    hand-computed magic numbers."""
    passport_check = str(_check_digit(passport_number))
    dob_check = str(_check_digit(dob))
    expiry_check = str(_check_digit(expiry))
    if personal_number_check is None:
        personal_number_check = str(_check_digit(personal_number))

    composite_data = (
        passport_number
        + passport_check
        + dob
        + dob_check
        + expiry
        + expiry_check
        + personal_number
        + personal_number_check
    )
    composite_check = str(_check_digit(composite_data))

    line2 = (
        passport_number
        + passport_check
        + nationality
        + dob
        + dob_check
        + sex
        + expiry
        + expiry_check
        + personal_number
        + personal_number_check
        + composite_check
    )
    assert len(line2) == 44
    return line2
