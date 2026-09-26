from types import SimpleNamespace

from mobile_world.runtime.app_helpers import system


def test_get_sent_sms_bodies_filters_phone_and_preserves_body(monkeypatch):
    adb_output = (
        "Row: 0 address=13900139000, date=300, body=latest, with comma\nsecond line\n"
        "Row: 1 address=10086, date=200, body=mentions 13900139000\n"
        "Row: 2 address=13900139000, date=100, body=older message"
    )
    captured = {}

    def fake_execute_adb(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(success=True, output=adb_output, error="")

    monkeypatch.setattr(system, "execute_adb", fake_execute_adb)
    controller = SimpleNamespace(device="emulator-5554")

    bodies = system.get_sent_sms_bodies_via_adb(controller, "13900139000")

    assert bodies == ["latest, with comma\nsecond line", "older message"]
    assert "content://sms/sent" in captured["command"]
    assert "shell 'content query" in captured["command"]
    assert "--projection address:date:body" in captured["command"]
    assert '--sort "date DESC"' in captured["command"]
    assert captured["kwargs"] == {"output": False, "root_required": True}


def test_get_sent_sms_bodies_ignores_missing_and_null_bodies(monkeypatch):
    adb_output = (
        "Row: 0 address=13900139000, date=300, body=NULL\nRow: 1 address=13900139000, date=200"
    )

    monkeypatch.setattr(
        system,
        "execute_adb",
        lambda *args, **kwargs: SimpleNamespace(success=True, output=adb_output, error=""),
    )

    bodies = system.get_sent_sms_bodies_via_adb(
        SimpleNamespace(device="emulator-5554"), "13900139000"
    )

    assert bodies == []


def test_get_sent_sms_bodies_returns_empty_list_when_adb_fails(monkeypatch):
    monkeypatch.setattr(
        system,
        "execute_adb",
        lambda *args, **kwargs: SimpleNamespace(
            success=False, output="", error="permission denied"
        ),
    )

    bodies = system.get_sent_sms_bodies_via_adb(
        SimpleNamespace(device="emulator-5554"), "13900139000"
    )

    assert bodies == []


def test_get_sent_sms_bodies_returns_empty_list_on_unexpected_error(monkeypatch):
    def raise_error(*args, **kwargs):
        raise RuntimeError("unexpected ADB failure")

    monkeypatch.setattr(system, "execute_adb", raise_error)

    bodies = system.get_sent_sms_bodies_via_adb(
        SimpleNamespace(device="emulator-5554"), "13900139000"
    )

    assert bodies == []
