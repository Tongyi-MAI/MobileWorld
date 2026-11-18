"""An agent's ENV_FAIL action must be a valid JSONAction and end the task cleanly."""

from PIL import Image

from mobile_world.core import runner
from mobile_world.runtime.utils.models import ENV_FAIL, JSONAction, Observation


def test_env_fail_is_a_valid_action_type():
    # gui_owl_1_5, memgui and qwen3vl return this when they give up on parsing.
    assert JSONAction(action_type=ENV_FAIL).action_type == ENV_FAIL


class _Env:
    tools = []

    def __init__(self):
        self.actions = 0

    def get_task_goal(self, task_type):
        return "goal"

    def initialize_task(self, task_name):
        return Observation(screenshot=Image.new("RGB", (8, 8)), ask_user_response=None)

    def execute_action(self, action):
        self.actions += 1

    def get_task_score(self, task_type):
        return 0.0, "not done"

    def tear_down_task(self, task_type):
        return None


class _GiveUpAgent:
    def initialize(self, goal):
        pass

    def predict(self, obs):
        return "llm parse error after multiple retries", JSONAction(action_type=ENV_FAIL)

    def get_total_token_usage(self):
        return {}

    def done(self):
        pass


def test_env_fail_terminates_and_is_scored(tmp_path):
    env = _Env()
    traj_logger = runner.TrajLogger(str(tmp_path), "Task")

    steps, score = runner._execute_single_task(env, _GiveUpAgent(), "Task", 50, traj_logger)

    # Before the fix, JSONAction(ENV_FAIL) raised inside predict(), so the task
    # produced no result and was left out of the success-rate denominator.
    assert (steps, score) == (1, 0.0)
    assert env.actions == 0
