"""Unit tests: run with `python -m pytest` (or `python tests/test_qsl_send.py`).

All fixtures use placeholder callsigns (N0CALL and the AA1AA/BB2BB pattern),
example.com addresses and invented names — never data from a real log.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qsl_send.adif import base_callsign, parse_adif  # noqa: E402
from qsl_send.fields import placeholders  # noqa: E402
from qsl_send.pipeline import safe_filename, select_qsos  # noqa: E402
from qsl_send.qrz import valid_email  # noqa: E402

SAMPLE = (
    "Some header text\n"
    "<ADIF_VER:5>3.1.1\n"
    "<eoh>\n"
    "<call:5>AA1AA<qso_date:8>20260823<time_on:4>1415<mode:3>SSB"
    "<freq:5>7.142<rst_sent:2>59<name:18>Ana Ejemplo Prueba"
    "<email:15>ana@example.com<band:3>40m<eor>\n"
    "<call:7>BB2BB/P<qso_date:8>20260823<time_on:4>1726<mode:3>SSB"
    "<freq:5>7.142<rst_sent:3>599<eor>\n"
    "<call:5>AA1AA<qso_date:8>20260823<time_on:4>1900<mode:3>SSB<eor>\n"
)


def _blank_template(path: Path) -> Path:
    """A stand-in for a real QSL image, at the size the default boxes assume."""
    from PIL import Image

    Image.new("RGB", (1583, 1061), "white").save(path, "JPEG")
    return path


def test_parses_records_and_skips_header():
    qsos = parse_adif(SAMPLE)
    assert len(qsos) == 3
    assert qsos[0].call == "AA1AA"
    assert qsos[0].get("name") == "Ana Ejemplo Prueba"
    assert qsos[0].get("adif_ver") == ""  # header fields excluded
    assert qsos[1].call == "BB2BB/P"


def test_values_containing_angle_brackets_survive():
    text = "<eoh><call:4>TEST<comment:7><hello><eor>"
    qsos = parse_adif(text)
    assert len(qsos) == 1
    assert qsos[0].get("comment") == "<hello>"


def test_field_lengths_are_byte_counts_not_character_counts():
    # ADI declares lengths in bytes. "Ana Bártolo" is 11 characters but 12
    # bytes in UTF-8, so a character-based slice would swallow the next tag.
    text = "<eoh><call:5>AA1AA<name:12>Ana Bártolo<mode:3>SSB<eor>"
    qso = parse_adif(text.encode("utf-8"))[0]
    assert qso.get("name") == "Ana Bártolo"
    assert qso.get("mode") == "SSB"


def test_parse_accepts_str_as_well_as_bytes():
    assert parse_adif("<eoh><call:5>AA1AA<eor>")[0].call == "AA1AA"


def test_latin1_values_do_not_crash_the_parser():
    qso = parse_adif(b"<eoh><call:5>AA1AA<name:6>Jos\xe9 B<eor>")[0]
    assert qso.call == "AA1AA"
    assert qso.get("name")


def test_base_callsign_strips_portable_parts():
    assert base_callsign("N0CALL/P") == "N0CALL"
    assert base_callsign("DL/N0CALL") == "N0CALL"
    assert base_callsign("N0CALL/QRP") == "N0CALL"
    assert base_callsign("n0call") == "N0CALL"


def test_placeholders_format_log_values_for_the_card():
    qso = parse_adif(SAMPLE)[0]
    v = placeholders(qso, my_callsign="N0CALL/A")
    assert v["date"] == "23/08/2026"
    assert v["utc"] == "14:15"
    assert v["qrg"] == "7.142"
    assert v["mode"] == "SSB"
    assert v["rst"] == "59"
    assert v["callsign"] == "AA1AA"
    assert v["my_callsign"] == "N0CALL/A"


def test_placeholders_tolerate_missing_and_malformed_fields():
    qso = parse_adif("<eoh><call:4>TEST<qso_date:3>abc<eor>")[0]
    v = placeholders(qso)
    assert v["date"] == "abc"  # unparseable dates pass through unchanged
    assert v["utc"] == ""
    assert v["name"] == ""


def test_name_first_is_the_first_given_name_titlecased():
    qso = parse_adif("<eoh><call:5>CC3CC<name:24>ANA DE LOS SANTOS PRUEBA<eor>")[0]
    assert placeholders(qso)["name_first"] == "Ana"


def test_name_first_falls_back_to_the_callsign_when_no_name_is_logged():
    qso = parse_adif("<eoh><call:5>DD4DD<eor>")[0]
    # A greeting must never render as "Hola !".
    assert placeholders(qso)["name_first"] == "DD4DD"


def test_titlecase_keeps_spanish_particles_lowercase():
    qso = parse_adif("<eoh><call:4>TEST<name:24>ANA DE LOS SANTOS PRUEBA<eor>")[0]
    assert placeholders(qso)["name_title"] == "Ana de los Santos Prueba"


def test_group_by_callsign_keeps_first_contact_only():
    qsos = parse_adif(SAMPLE)
    assert len(select_qsos(qsos, "qso")) == 3
    grouped = select_qsos(qsos, "callsign")
    assert [q.call for q in grouped] == ["AA1AA", "BB2BB/P"]
    assert grouped[0].get("time_on") == "1415"


def test_safe_filename_removes_path_characters():
    assert safe_filename("BB2BB/P_20260823") == "BB2BB_P_20260823"
    assert safe_filename("../../etc/passwd") == "etc_passwd"
    assert safe_filename("") == "card"


def test_valid_email():
    assert valid_email("operator@example.com")
    assert not valid_email("LoTW - eQSL - Mail")
    assert not valid_email("Directo")
    assert not valid_email("")


def test_contacts_file_accepts_both_entry_forms(tmp_path):
    from qsl_send.contacts import load_contacts

    path = tmp_path / "contacts.yaml"
    path.write_text(
        "AA1AA: plain@example.com\n"
        "BB2BB:\n"
        "  email: mapped@example.com\n"
        "  name: Mapped Name\n",
        encoding="utf-8",
    )
    contacts, warnings = load_contacts(path)
    assert warnings == []
    assert contacts["AA1AA"].email == "plain@example.com"
    assert contacts["BB2BB"].email == "mapped@example.com"
    assert contacts["BB2BB"].name == "Mapped Name"


def test_contacts_entries_are_keyed_on_the_base_callsign(tmp_path):
    from qsl_send.contacts import load_contacts

    path = tmp_path / "contacts.yaml"
    # An entry written as the base call must also cover /A and /P in the log.
    path.write_text("CC3CC: base@example.com\n", encoding="utf-8")
    contacts, _ = load_contacts(path)
    assert base_callsign("CC3CC/A") in contacts


def test_contacts_reject_values_that_are_not_addresses(tmp_path):
    from qsl_send.contacts import load_contacts

    path = tmp_path / "contacts.yaml"
    path.write_text("AA1AA: Directo\n", encoding="utf-8")
    contacts, warnings = load_contacts(path)
    assert contacts == {}
    assert any("does not look valid" in w for w in warnings)


def test_contacts_override_wins_over_the_log(tmp_path):
    from qsl_send.config import load_config
    from qsl_send.contacts import Contact
    from qsl_send.pipeline import generate_cards

    adif = tmp_path / "log.adi"
    adif.write_text(SAMPLE, encoding="utf-8")

    summary = generate_cards(
        load_config(None),
        adif_path=adif,
        template_path=_blank_template(tmp_path / "template.jpg"),
        output_dir=tmp_path / "out",
        use_qrz=False,
        # AA1AA already has ana@example.com in the log; BB2BB/P has none.
        contacts={
            "AA1AA": Contact("AA1AA", email="curated@example.com"),
            "BB2BB": Contact("BB2BB", email="found@example.com", name="Found Name"),
        },
    )
    by_call = {r.callsign: r for r in summary.results}
    assert by_call["AA1AA"].email == "curated@example.com"
    assert by_call["AA1AA"].email_source == "override"
    # The override reaches a portable callsign via its base call.
    assert by_call["BB2BB/P"].email == "found@example.com"
    assert by_call["BB2BB/P"].name == "Found Name"
    assert summary.with_email == 3


def test_end_to_end_generates_cards_and_manifest(tmp_path):
    import csv

    from qsl_send.config import load_config
    from qsl_send.pipeline import generate_cards
    from qsl_send.report import write_manifest

    adif = tmp_path / "log.adi"
    adif.write_text(SAMPLE, encoding="utf-8")

    cfg = load_config(None)
    summary = generate_cards(
        cfg,
        adif_path=adif,
        template_path=_blank_template(tmp_path / "template.jpg"),
        output_dir=tmp_path / "out",
        use_qrz=False,
    )
    assert summary.qsos_read == 3
    assert summary.cards_written == 3
    assert summary.with_email == 1

    paths = write_manifest(summary, tmp_path / "out")
    rows = list(csv.DictReader(paths["csv"].open(encoding="utf-8-sig")))
    assert len(rows) == 3
    assert rows[0]["email"] == "ana@example.com"
    assert rows[1]["status"] == "no_email"
    for row in rows:
        assert (tmp_path / "out" / row["card_file"]).is_file()

    # Two QSOs with the same callsign must not overwrite each other's card.
    assert rows[0]["card_file"] != rows[2]["card_file"]


if __name__ == "__main__":
    import subprocess

    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))
