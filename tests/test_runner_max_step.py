"""`--max-round` omitted (-1, "unlimited") must not stop a task after one step."""

import pytest
from PIL import Image

from mobile_world.core import runner
from mobile_world.runtime.utils.models import JSONAction, Observation


class _Env:
    tools = []

    def __init__(self):
        self.actions = 0

    def get_task_goal(self, task_type):
        return "goal"

    def _obs(self):
        return Observation(screenshot=Image.new("RGB", (8, 8)), ask_user_response=None)

    def initialize_task(self, task_name):
        return self._obs()

    def execute_action(self, action):
        self.actions += 1
        return self._obs()

    def get_task_score(self, task_type):
        return 1.0, "ok"

    def tear_down_task(self, task_type):
        return None


class _Agent:
    """Clicks four times, then finishes on step 5."""

    def __init__(self):
        self.n = 0

    def initialize(self, goal):
        self.n = 0

    def predict(self, obs):
        self.n += 1
        if self.n >= 5:
            return "done", JSONAction(action_type="finished")
        return "click", JSONAction(action_type="click", x=1, y=1)

    def get_total_token_usage(self):
        return {}

    def done(self):
        pass


def _run(tmp_path, max_step):
    env = _Env()
    traj_logger = runner.TrajLogger(str(tmp_path), "Task")
    steps, _ = runner._execute_single_task(env, _Agent(), "Task", max_step, traj_logger)
    return steps, env.actions


@pytest.mark.parametrize("max_step", [-1, 0])
def test_non_positive_max_step_is_unlimited(tmp_path, max_step):
    assert _run(tmp_path, max_step) == (5, 4)


def test_positive_max_step_still_caps_the_episode(tmp_path):
    assert _run(tmp_path, 2) == (2, 2)
