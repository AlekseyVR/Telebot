from utils.system_monitor import tail_file


def test_tail_returns_last_lines(tmp_path):
    p = tmp_path / "app.log"
    p.write_bytes(b"line1\nline2\nline3\nline4\n")
    assert tail_file(str(p), 2) == b"line3\nline4\n"


def test_tail_more_than_file_returns_whole_file(tmp_path):
    p = tmp_path / "app.log"
    p.write_bytes(b"a\nb\n")
    assert tail_file(str(p), 10) == b"a\nb\n"


def test_tail_zero_returns_empty(tmp_path):
    p = tmp_path / "app.log"
    p.write_bytes(b"a\nb\n")
    assert tail_file(str(p), 0) == b""
