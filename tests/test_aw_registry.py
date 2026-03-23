"""Tests for AWTaskRegistry that discovers and wraps AndroidWorld tasks."""

from unittest.mock import MagicMock, patch

import pytest

from mobile_world.tasks.aw_registry import AWTaskRegistry


def _make_mock_task_class(name="MockTask"):
    cls = MagicMock()
    cls.__name__ = name
    cls.generate_random_params.return_value = {"param": "value"}
    instance = MagicMock()
    instance.app_names = ("com.example",)
    instance.goal = f"Goal for {name}"
    instance.complexity = 0.5
    instance.__class__ = type(name, (), {})
    cls.return_value = instance
    return cls


class TestAWTaskRegistry:
    @patch("mobile_world.tasks.aw_registry.ANDROID_TASK_REGISTRY", {
        "TaskA": _make_mock_task_class("TaskA"),
        "TaskB": _make_mock_task_class("TaskB"),
    })
    def test_loads_all_tasks(self):
        registry = AWTaskRegistry()
        assert len(registry.tasks) == 2
        assert "TaskA" in registry.tasks
        assert "TaskB" in registry.tasks

    @patch("mobile_world.tasks.aw_registry.ANDROID_TASK_REGISTRY", {
        "TaskA": _make_mock_task_class("TaskA"),
    })
    def test_tasks_are_aw_task_wrappers(self):
        from mobile_world.tasks.aw_task_wrapper import AWTaskWrapper
        registry = AWTaskRegistry()
        assert isinstance(registry.tasks["TaskA"], AWTaskWrapper)

    @patch("mobile_world.tasks.aw_registry.ANDROID_TASK_REGISTRY", {
        "TaskA": _make_mock_task_class("TaskA"),
    })
    def test_seed_propagates_to_wrappers(self):
        registry = AWTaskRegistry(seed=42)
        assert registry.tasks["TaskA"]._seed == 42

    @patch("mobile_world.tasks.aw_registry.ANDROID_TASK_REGISTRY", {})
    def test_empty_registry(self):
        registry = AWTaskRegistry()
        assert len(registry.tasks) == 0

    @patch("mobile_world.tasks.aw_registry.ANDROID_TASK_REGISTRY", {
        "BadTask": MagicMock(side_effect=Exception("construction error")),
    })
    def test_skips_tasks_that_fail_to_construct(self):
        """Tasks that fail during AWTaskWrapper construction should be skipped."""
        registry = AWTaskRegistry()
        assert len(registry.tasks) == 0
