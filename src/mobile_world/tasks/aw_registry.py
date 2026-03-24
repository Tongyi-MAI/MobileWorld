"""Registry that discovers AndroidWorld tasks and wraps them as BaseTask."""

import sys
from pathlib import Path

from loguru import logger

from mobile_world.tasks.aw_task_wrapper import AWTaskWrapper

# Add android_world to sys.path if not already importable
_aw_path = Path(__file__).resolve().parents[3] / "resources" / "android_world"
if _aw_path.exists() and str(_aw_path) not in sys.path:
    sys.path.insert(0, str(_aw_path))

try:
    from android_world.registry import TaskRegistry as AWNativeRegistry
    _aw_native_registry = AWNativeRegistry()
    ANDROID_TASK_REGISTRY = _aw_native_registry.ANDROID_TASK_REGISTRY
except ImportError:
    logger.warning(
        "android_world package not found. AndroidWorld tasks will not be available. "
        "Ensure the submodule is initialized: git submodule update --init"
    )
    ANDROID_TASK_REGISTRY = {}
except Exception as e:
    logger.warning(f"Failed to load android_world registry: {e}")
    ANDROID_TASK_REGISTRY = {}


class AWTaskRegistry:
    """Loads AndroidWorld TaskEval classes and wraps them as BaseTask.

    Exposes the same `tasks` dict interface as TaskRegistry so the server
    code works unchanged.
    """

    def __init__(self, seed: int = None):
        self.tasks: dict[str, AWTaskWrapper] = {}
        self._seed = seed
        self._load_android_world_tasks()

    def _load_android_world_tasks(self):
        logger.info(f"Loading AndroidWorld tasks (seed={self._seed})...")

        for task_name, task_class in ANDROID_TASK_REGISTRY.items():
            try:
                wrapper = AWTaskWrapper(
                    task_eval_class=task_class,
                    seed=self._seed,
                )
                self.tasks[task_name] = wrapper
            except Exception as e:
                logger.error(f"Failed to load AndroidWorld task '{task_name}': {e}")

        logger.info(f"Loaded {len(self.tasks)} AndroidWorld tasks")

    def get_task(self, task_name: str):
        if task_name not in self.tasks:
            logger.error(
                f"Task '{task_name}' not found. Available tasks: {list(self.tasks.keys())}"
            )
            raise KeyError(f"Task '{task_name}' not found in AndroidWorld registry")
        return self.tasks[task_name]

    def list_tasks(self) -> list:
        return list(self.tasks.keys())

    def has_task(self, task_name: str) -> bool:
        return task_name in self.tasks
