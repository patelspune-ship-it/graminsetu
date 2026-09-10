import pytest

from app.data.amenities import (
    ANCHOR_COLUMNS,
    EXPECTED_COLUMN_COUNT,
    build_amenities,
    clean_village_code,
    decode_facility,
    decode_power,
    parse_distance_code,
    parse_header,
    parse_hours,
    parse_number,
    parse_rows,
    parse_status,
    parse_text,
    resolve_csv_path,
)


def make_header(overrides: dict[int, str] | None = None) -> list[str]:
    header = [f"col{index}" for index in range(EXPECTED_COLUMN_COUNT)]
    for index, label in ANCHOR_COLUMNS.items():
        header[index] = label
    for index, label in (overrides or {}).items():
        header[index] = label
    return header


def make_row(overrides: dict[int, str] | None = None) -> list[str]:
    row = ["NA"] * EXPECTED_COLUMN_COUNT
    for index, value in (overrides or {}).items():
        row[index] = value
    return row


def write_csv(tmp_path, rows: list[list[str]], filename="DCHB_Village_Amenities-Maharashtra-Nashik-516.csv"):
    path = tmp_path / filename
    path.write_text(
        "\n".join(",".join(f'"{cell}"' for cell in row) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def test_clean_village_code_strips_apostrophe_and_whitespace():
    assert clean_village_code("'549593") == "549593"
    assert clean_village_code("  '549593  ") == "549593"


def test_clean_village_code_normalizes_leading_zeros():
    assert clean_village_code("'0549593") == "549593"


def test_clean_village_code_passes_through_unparseable_values():
    # Not raised: an unparseable code simply won't match a village_lgd,
    # which is what drops the match rate (the actual fail-loud gate).
    assert clean_village_code("'Total") == "Total"


def test_parse_status_decodes_known_codes():
    assert parse_status("1") is True
    assert parse_status("2") is False
    assert parse_status("NA") is None
    assert parse_status("") is None


def test_parse_distance_code_only_accepts_abc():
    assert parse_distance_code("a") == "a"
    assert parse_distance_code("C") == "c"
    assert parse_distance_code("NA") is None
    assert parse_distance_code("") is None


def test_decode_facility_available_has_no_distance():
    facility = decode_facility("1", "NA")
    assert facility == {
        "available": True,
        "raw_status": "1",
        "distance_code": None,
        "distance_range_km": None,
    }


def test_decode_facility_unavailable_has_distance_range():
    facility = decode_facility("2", "b")
    assert facility == {
        "available": False,
        "raw_status": "2",
        "distance_code": "b",
        "distance_range_km": "5-10km",
    }


def test_decode_facility_unknown_status_keeps_raw():
    facility = decode_facility("NA", "NA")
    assert facility["available"] is None
    assert facility["raw_status"] == "NA"


def test_decode_power_parses_hours():
    power = decode_power("1", "12", "10")
    assert power == {
        "available": True,
        "raw_status": "1",
        "hours_summer": 12,
        "hours_winter": 10,
    }


def test_decode_power_treats_na_hours_as_unknown():
    power = decode_power("2", "0", "NA")
    assert power["hours_summer"] == 0
    assert power["hours_winter"] is None


def test_parse_hours_handles_blank_and_na():
    assert parse_hours("12") == 12
    assert parse_hours("NA") is None
    assert parse_hours("") is None
    assert parse_hours("abc") is None


def test_parse_number_handles_blank_and_na():
    assert parse_number("83.9") == 83.9
    assert parse_number("NA") is None
    assert parse_number("") is None


def test_parse_text_treats_na_as_missing():
    assert parse_text("Onion") == "Onion"
    assert parse_text("NA") is None
    assert parse_text("  ") is None


def test_resolve_csv_path_globs_trailing_number(tmp_path):
    write_csv(tmp_path, [make_header()], filename="DCHB_Village_Amenities-Maharashtra-Nashik-999.csv")

    resolved = resolve_csv_path("Nashik", raw_dir=tmp_path)

    assert resolved.name == "DCHB_Village_Amenities-Maharashtra-Nashik-999.csv"


def test_resolve_csv_path_missing_file_raises(tmp_path):
    with pytest.raises(ValueError, match="No amenities CSV"):
        resolve_csv_path("Nashik", raw_dir=tmp_path)


def test_resolve_csv_path_rejects_multiple_matches(tmp_path):
    write_csv(tmp_path, [make_header()], filename="DCHB_Village_Amenities-Maharashtra-Nashik-100.csv")
    write_csv(tmp_path, [make_header()], filename="DCHB_Village_Amenities-Maharashtra-Nashik-200.csv")

    with pytest.raises(ValueError, match="Multiple amenities CSVs"):
        resolve_csv_path("Nashik", raw_dir=tmp_path)


def test_parse_header_rejects_wrong_column_count(tmp_path):
    path = write_csv(tmp_path, [["a", "b", "c"]])

    with pytest.raises(ValueError, match="expected 396 columns"):
        parse_header(path)


def test_parse_header_rejects_moved_anchor_column(tmp_path):
    path = write_csv(tmp_path, [make_header({6: "Something Else"})])

    with pytest.raises(ValueError, match="Village Code"):
        parse_header(path)


def test_parse_rows_skips_blank_rows(tmp_path):
    header = make_header()
    data_row = make_row({6: "'123", 7: "Example"})
    blank_row = [""] * EXPECTED_COLUMN_COUNT

    path = write_csv(tmp_path, [header, data_row, blank_row])

    rows = parse_rows(path)

    assert len(rows) == 1
    line, row = rows[0]
    assert line == 2
    assert row[6] == "'123"


def test_build_amenities_decodes_all_sections(tmp_path):
    header = make_header()
    row = make_row({
        6: "'549593",
        7: "Bardipada",
        # Commercial power: available, 8h summer, 6h winter.
        363: "1", 364: "8", 365: "6",
        # Black topped road available.
        301: "1", 302: "NA",
        # Mandi not available, 5-10km away.
        325: "2", 326: "b",
        # ATM not available, <5km away.
        313: "2", 314: "a",
        # Crops.
        369: "Onion", 372: "NA", 375: "Grapes",
        # Land.
        386: "83.9", 387: "0", 388: "83.9",
        # Connectivity.
        394: "Wazda", 395: "12",
    })

    path = write_csv(tmp_path, [header, row])
    amenities = build_amenities(row, path, line=2)

    assert amenities["power"]["commercial"] == {
        "available": True,
        "raw_status": "1",
        "hours_summer": 8,
        "hours_winter": 6,
    }
    assert amenities["roads"]["black_topped"]["available"] is True
    assert amenities["markets"]["mandis_regular_market"] == {
        "available": False,
        "raw_status": "2",
        "distance_code": "b",
        "distance_range_km": "5-10km",
    }
    assert amenities["finance"]["atm"]["distance_range_km"] == "<5km"
    assert amenities["crops"]["agricultural_commodities"] == {
        "first": "Onion",
        "second": None,
        "third": "Grapes",
    }
    assert amenities["land"]["net_area_sown_ha"] == 83.9
    assert amenities["connectivity"]["nearest_town_name"] == "Wazda"
    assert amenities["connectivity"]["nearest_town_distance_km"] == 12.0
    assert amenities["source"]["csv_line"] == 2
