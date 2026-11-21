"""Trace step previews must be readable and must never carry unmasked personal data (hotfix v6)."""
from dq.trace import preview


def test_dict_preview_masks_names_dob_ids_and_contacts():
    out = preview({"status": "success", "applicant_id": "APP-2003",
                   "documents": {"pan": {"name": "DAVID JOSEPH", "dob": "1979-02-14", "number": "ABCD1234E"}},
                   "phone": "9876543210", "email": "david.joseph@example.com"})
    for raw in ("DAVID JOSEPH", "1979-02-14", "ABCD1234E", "9876543210", "david.joseph@example.com"):
        assert raw not in out, raw
    assert "APP-2003" in out          # business ids stay readable
    assert "{'" not in out and "':" not in out   # no Python dict syntax on screen


def test_list_and_numbers_are_readable():
    out = preview({"status": "success", "quotes": [{"supplier": "A", "price": 210.5}, {"supplier": "B", "price": 220}]})
    assert out.startswith("quotes: 2 items")
    assert "210.5" in out


def test_text_and_length_cap():
    assert preview("plain text") == "plain text"
    assert len(preview({"k": "x" * 5000}, 100)) <= 100
