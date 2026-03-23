"""Tests for AWTaskWrapper that wraps AndroidWorld TaskEval as MobileWorld BaseTask."""

import random
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from mobile_world.tasks.aw_task_wrapper import AWTaskWrapper
from mobile_world.tasks.base import BaseTask


def _make_mock_task_eval_class(
    app_names=("com.example.app",),
    template="Do something with {param1}",
    complexity=0.5,
    goal="Do something with value1",
):
    """Create a mock TaskEval class with the expected interface."""
    mock_class = MagicMock()
    mock_class.__name__ = "MockTaskEval"

    mock_class.generate_random_params.return_value = {"param1": "value1"}

    mock_instance = MagicMock()
    mock_instance.app_names = app_names
    mock_instance.goal = goal
    mock_instance.complexity = complexity
    mock_instance.initialize_task = MagicMock()
    mock_instance.is_successful = MagicMock(return_value=1.0)
    mock_instance.tear_down = MagicMock()
    mock_instance.__class__ = type("MockTaskEval", (), {})
    mock_class.return_value = mock_instance

    return mock_class


class TestAWTaskWrapperInit:
    def test_creates_wrapper_with_random_params(self):
        mock_class = _make_mock_task_eval_class()
        wrapper = AWTaskWrapper(mock_class)
        assert wrapper.name == "MockTaskEval"
        mock_class.generate_random_params.assert_called_once()

    def test_creates_wrapper_with_fixed_params(self):
        mock_class = _make_mock_task_eval_class()
        wrapper = AWTaskWrapper(mock_class, params={"param1": "fixed"})
        mock_class.generate_random_params.assert_not_called()
        mock_class.assert_called_once_with({"param1": "fixed"})

    def test_creates_wrapper_with_seed(self):
        mock_class = _make_mock_task_eval_class()
        wrapper = AWTaskWrapper(mock_class, seed=42)
        mock_class.generate_random_params.assert_called_once()

    def test_seed_produces_deterministic_params(self):
        """Same seed should produce same random state."""
        mock_class = _make_mock_task_eval_class()
        states = []
        def capture_state():
            states.append(random.getstate())
            return {"param1": "value1"}
        mock_class.generate_random_params.side_effect = capture_state

        AWTaskWrapper(mock_class, seed=42)
        AWTaskWrapper(mock_class, seed=42)
        assert states[0] == states[1]


class TestAWTaskWrapperProperties:
    def test_app_names_returns_set(self):
        mock_class = _make_mock_task_eval_class(app_names=("app1", "app2"))
        wrapper = AWTaskWrapper(mock_class)
        assert wrapper.app_names == {"app1", "app2"}

    def test_goal_delegates_to_task_eval(self):
        mock_class = _make_mock_task_eval_class(goal="Test goal text")
        wrapper = AWTaskWrapper(mock_class)
        assert wrapper.goal == "Test goal text"

    def test_snapshot_tag_is_aw_init_state(self):
        mock_class = _make_mock_task_eval_class()
        wrapper = AWTaskWrapper(mock_class)
        assert wrapper.snapshot_tag == "aw_init_state"

    def test_task_tags_contains_android_world(self):
        mock_class = _make_mock_task_eval_class()
        wrapper = AWTaskWrapper(mock_class)
        assert "android_world" in wrapper.task_tags

    def test_complexity_delegates(self):
        mock_class = _make_mock_task_eval_class(complexity=0.7)
        wrapper = AWTaskWrapper(mock_class)
        assert wrapper.complexity == 0.7

    def test_start_on_home_screen_is_false(self):
        mock_class = _make_mock_task_eval_class()
        wrapper = AWTaskWrapper(mock_class)
        assert wrapper.start_on_home_screen is False


class TestAWTaskWrapperLifecycle:
    def test_initialize_task_loads_snapshot(self):
        mock_class = _make_mock_task_eval_class()
        wrapper = AWTaskWrapper(mock_class)
        controller = MagicMock()
        controller.load_snapshot.return_value = True

        wrapper.initialize_task(controller)

        controller.load_snapshot.assert_called_once_with("aw_init_state")
        assert wrapper.initialized is True

    def test_initialize_task_calls_task_eval_initialize(self):
        mock_class = _make_mock_task_eval_class()
        wrapper = AWTaskWrapper(mock_class)
        controller = MagicMock()
        controller.load_snapshot.return_value = True

        wrapper.initialize_task(controller)

        wrapper._task_eval.initialize_task.assert_called_once()

    def test_initialize_task_does_not_call_base_initialize(self):
        """Should NOT delegate to BaseTask.initialize_task (which runs MW cleanup)."""
        mock_class = _make_mock_task_eval_class()
        wrapper = AWTaskWrapper(mock_class)
        controller = MagicMock()
        controller.load_snapshot.return_value = True

        with patch.object(BaseTask, "initialize_task") as mock_base_init:
            wrapper.initialize_task(controller)
            mock_base_init.assert_not_called()

    def test_is_successful_delegates(self):
        mock_class = _make_mock_task_eval_class()
        mock_class.return_value.is_successful.return_value = 0.5
        wrapper = AWTaskWrapper(mock_class)
        controller = MagicMock()
        controller.load_snapshot.return_value = True
        wrapper.initialize_task(controller)

        score = wrapper.is_successful(controller)
        assert score == 0.5

    def test_tear_down_delegates_and_cleans_up(self):
        mock_class = _make_mock_task_eval_class()
        wrapper = AWTaskWrapper(mock_class)
        controller = MagicMock()
        controller.load_snapshot.return_value = True
        wrapper.initialize_task(controller)

        wrapper.tear_down(controller)
        wrapper._task_eval.tear_down.assert_called_once()
        assert wrapper.initialized is False
