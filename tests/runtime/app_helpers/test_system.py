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


def _fake_sent_sms(monkeypatch, body):
    adb_output = f"Row: 0 address=+14058298746, date=100, body={body}"
    monkeypatch.setattr(
        system,
        "execute_adb",
        lambda *args, **kwargs: SimpleNamespace(success=True, output=adb_output, error=""),
    )


def test_check_sms_list_content_accepts_space_after_comma(monkeypatch):
    controller = SimpleNamespace(device="emulator-5554")
    for body in ("10/04/2025,10/10/2025", "10/04/2025, 10/10/2025"):
        _fake_sent_sms(monkeypatch, body)
        assert system.check_sms_via_adb(
            controller, "+14058298746", ["10/04/2025", "10/10/2025"]
        )


def test_check_conference_and_send_sms_tasks_use_list_content():
    from mobile_world.tasks.definitions.calendar.check_conference_and_send_sms_1 import (
        CheckConferenceAndSendSmsTask1,
    )
    from mobile_world.tasks.definitions.calendar.check_conference_and_send_sms_2 import (
        CheckConferenceAndSendSmsTask2,
    )

    for task_cls in (CheckConferenceAndSendSmsTask1, CheckConferenceAndSendSmsTask2):
        assert isinstance(task_cls.expected_message_content, list)
