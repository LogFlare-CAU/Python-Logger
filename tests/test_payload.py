from logflare_logger.payload import LogPayload


def test_payload_uses_backend_field_names() -> None:
    payload = LogPayload(error_type="ValueError", level="ERROR", message="bad value")

    assert payload.as_json() == {
        "errortype": "ValueError",
        "level": "ERROR",
        "message": "bad value",
    }


def test_payload_serializes_null_error_type() -> None:
    payload = LogPayload(error_type=None, level="WARNING", message="plain")

    assert payload.as_json() == {
        "errortype": None,
        "level": "WARNING",
        "message": "plain",
    }


def test_test_payload_includes_test_flag_only_when_enabled() -> None:
    payload = LogPayload(error_type="ConnectionTest", level="INFO", message="test", test=True)

    assert payload.as_json() == {
        "errortype": "ConnectionTest",
        "level": "INFO",
        "message": "test",
        "test": True,
    }
