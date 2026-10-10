from utils.system_monitor import is_tcp_open


class _FakeSock:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_is_tcp_open_ok(monkeypatch):
    monkeypatch.setattr(
        "utils.system_monitor.socket.create_connection",
        lambda addr, timeout: _FakeSock(),
    )
    assert is_tcp_open("127.0.0.1:5432") is True


def test_is_tcp_open_fail(monkeypatch):
    def _refused(addr, timeout):
        raise OSError("Connection refused")

    monkeypatch.setattr("utils.system_monitor.socket.create_connection", _refused)
    assert is_tcp_open("127.0.0.1:5432") is False


def test_is_tcp_open_bad_format():
    assert is_tcp_open("no-port") is False
