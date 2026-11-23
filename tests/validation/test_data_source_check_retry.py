"""Downloads by the reference readers are tried again on a connection error, never on an answer."""

from urllib.error import HTTPError

import pytest

from data_source_check.reference import _retry


def test_a_connection_error_is_tried_again_and_an_answer_is_not() -> None:
    calls = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("The read operation timed out")
        return "done"

    assert _retry.again(flaky, pause=0) == "done" and len(calls) == 3

    def down() -> None:
        calls.append(1)
        raise ConnectionResetError(54, "Connection reset by peer")

    calls.clear()
    with pytest.raises(ConnectionResetError):
        _retry.again(down, attempts=2, pause=0)
    assert len(calls) == 2

    for answer in (HTTPError("u", 404, "Not Found", None, None), FileNotFoundError("no copy")):  # type: ignore[arg-type]
        calls.clear()

        def refuse(error: Exception = answer) -> None:
            calls.append(1)
            raise error

        with pytest.raises(type(answer)):
            _retry.again(refuse, pause=0)
        assert len(calls) == 1
