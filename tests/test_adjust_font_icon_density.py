from types import SimpleNamespace

import pytest

from mobile_world.runtime.app_helpers import system
from mobile_world.tasks.definitions.settings import adjust_font_icon_max, adjust_font_icon_min


@pytest.mark.parametrize(
    ("physical_density", "min_dimension", "expected"),
    [
        (280, 720, (238, 360)),  # ARM redroid: 720x1600 at 280 DPI
    ],
)
def test_display_size_density_bounds(monkeypatch, physical_density, min_dimension, expected):
    monkeypatch.setattr(system, "get_physical_density", lambda _controller: physical_density)
    monkeypatch.setattr(system, "get_min_screen_dimension", lambda _controller: min_dimension)

    assert system.get_display_size_density_bounds(SimpleNamespace()) == expected


@pytest.mark.parametrize(
    ("module", "task_class", "font_scale", "density", "bounds", "redroid"),
    [
        (
            adjust_font_icon_min,
            adjust_font_icon_min.AdjustFontIconMinimumTask,
            0.85,
            238,
            (238, 360),
            True,
        ),
        (
            adjust_font_icon_max,
            adjust_font_icon_max.AdjustFontIconMaximumTask,
            2.0,
            360,
            (238, 360),
            True,
        ),
        (
            adjust_font_icon_min,
            adjust_font_icon_min.AdjustFontIconMinimumTask,
            0.85,
            356,
            None,
            False,
        ),
        (
            adjust_font_icon_max,
            adjust_font_icon_max.AdjustFontIconMaximumTask,
            2.0,
            540,
            None,
            False,
        ),
    ],
)
def test_verifier_accepts_arm_and_legacy_x86_bounds(
    monkeypatch, module, task_class, font_scale, density, bounds, redroid
):
    monkeypatch.setattr(module, "get_font_scale", lambda _controller: font_scale)
    monkeypatch.setattr(module, "get_display_density", lambda _controller: density)
    monkeypatch.setattr(module, "is_redroid", lambda _device: redroid)
    if redroid:
        monkeypatch.setattr(module, "get_display_size_density_bounds", lambda _controller: bounds)
    else:
        monkeypatch.setattr(
            module,
            "get_display_size_density_bounds",
            lambda _controller: pytest.fail("legacy x86 must not use dynamic density bounds"),
        )
    task = task_class()
    task.initialized = True
    task._original_font_scale = 1.0
    task._original_density = 420

    assert task.is_successful(SimpleNamespace(device="emulator-5554")) == (1.0, "Success")


@pytest.mark.parametrize(
    ("module", "task_class", "font_scale", "legacy_density"),
    [
        (adjust_font_icon_min, adjust_font_icon_min.AdjustFontIconMinimumTask, 0.85, 356),
        (adjust_font_icon_max, adjust_font_icon_max.AdjustFontIconMaximumTask, 2.0, 540),
    ],
)
def test_verifier_preserves_exact_legacy_fallback(
    monkeypatch, module, task_class, font_scale, legacy_density
):
    monkeypatch.setattr(module, "get_font_scale", lambda _controller: font_scale)
    monkeypatch.setattr(module, "get_display_size_density_bounds", lambda _controller: (0, 0))
    monkeypatch.setattr(module, "is_redroid", lambda _device: True)
    task = task_class()
    task.initialized = True
    task._original_font_scale = 1.0
    task._original_density = 420

    monkeypatch.setattr(module, "get_display_density", lambda _controller: legacy_density)
    controller = SimpleNamespace(device="emulator-5554")
    assert task.is_successful(controller) == (1.0, "Success")

    monkeypatch.setattr(module, "get_display_density", lambda _controller: legacy_density - 1)
    score, _reason = task.is_successful(controller)
    assert score == 0.0
