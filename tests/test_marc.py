from __future__ import annotations

from z3950_search_for_marc.marc import decode_yaz_output, extract_marc_record, sanitize_filename


def test_decode_yaz_output_prefers_legacy_console_decoding() -> None:
    text = (
        "599    $a Maskinellt genererad post. "
        "Ändra kod för fullständighetsnivå (leader/17), annars kommer "
        "manuellt gjorda ändringar att försvinna."
    )
    encoded = text.encode("cp850")

    decoded = decode_yaz_output(encoded)

    assert "Ändra" in decoded
    assert "fullständighetsnivå" in decoded


def test_extract_marc_record_respects_trim_toggle() -> None:
    raw = "\n".join(
        [
            "001    12345",
            "245 10 $a Test title",
            "950    $a Hidden field",
        ]
    )

    trimmed = extract_marc_record(raw, trim_records=True)
    untrimmed = extract_marc_record(raw, trim_records=False)

    assert trimmed is not None
    assert untrimmed is not None
    assert [field.tag for field in trimmed.fields] == ["245"]
    assert [field.tag for field in untrimmed.fields] == ["001", "245", "950"]


def test_sanitize_filename_removes_unsafe_characters() -> None:
    assert sanitize_filename('Author: "Title"/Name?') == "Author_Title_Name"
