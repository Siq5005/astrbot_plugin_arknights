from core import render


def test_capture_is_usable_rejects_empty_file(tmp_path):
    empty = tmp_path / "empty.jpg"
    empty.write_bytes(b"")
    assert render._capture_is_usable(empty) is False


def test_capture_is_usable_accepts_non_empty_file(tmp_path):
    ok = tmp_path / "ok.jpg"
    ok.write_bytes(b"\xff\xd8\xff")
    assert render._capture_is_usable(ok) is True


def test_capture_is_usable_rejects_missing_file(tmp_path):
    assert render._capture_is_usable(tmp_path / "nope.jpg") is False


def test_max_capture_px_stays_under_the_chromium_limit():
    # Chromium writes an empty file past 65535px; the margin must hold.
    assert render.MAX_CAPTURE_PX < 65535
