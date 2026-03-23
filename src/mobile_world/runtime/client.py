import base64
import copy
import json
import os
import time
from io import BytesIO

import backoff
import requests
from loguru import logger
from markdownify import markdownify
from PIL import Image

from mobile_world.runtime.mcp_server import init_mcp_clients
from mobile_world.runtime.utils.models import MCP, NAVIGATE_HOME, JSONAction, Observation, Response
from mobile_world.runtime.utils.trajectory_logger import SCORE_FILE_NAME
from mobile_world.tasks.registry import TaskRegistry

TASK_META_DATA_PATH = "./new_task_metadata.json"
DEFAULT_MAX_STEP = 15


class AndroidEnvClient:
    """Client for interacting with the new Android environment server (server.py)."""

    def __init__(
        self,
        url: str = "http://localhost:8000",
        device: str = "emulator-5554",
        step_wait_time: float = 1.0,
    ):
        logger.info(
            "Setting up Android environment using new server design - Initial setup may take"
            " 5-10 minutes. Please wait..."
        )
        self.base_url = url
        self.device = device
        self.step_wait_time = step_wait_time
        self._task_metadata = {}
        self._current_task_type = None
        self._initialized = False
        self._task_registry = TaskRegistry()
        self.tools = []

    def _ensure_initialized(self):
        """Ensure the device is initialized."""
        if not self._initialized:
            # Initialize the device controller
            init_data = {
                "device": self.device,
            }
            response = requests.post(f"{self.base_url}/init", json=init_data)
            response.raise_for_status()
            self._initialized = True

    def switch_suite_family(self, target_family: str, seed: int = None) -> dict:
        """Switch to a different suite family.

        Args:
            target_family: Either "mobile_world" or "android_world"
            seed: Optional random seed for reproducible AndroidWorld params

        Returns:
            dict: Response from the suite family switch endpoint

        Raises:
            RuntimeError: If the suite family switch fails
        """
        logger.info(f"Switching to suite_family: {target_family}")

        try:
            params = {"target_family": target_family}
            if seed is not None:
                params["seed"] = seed

            response = requests.post(
                f"{self.base_url}/suite_family/switch",
                params=params,
                timeout=300,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Suite family switch result: {result}")

            if result.get("switched"):
                logger.info(
                    f"Successfully switched to {target_family} "
                    f"(AVD: {result.get('avd_name')}, Device: {result.get('emulator_device_id')})"
                )
                self._initialized = False

            return result
        except requests.RequestException as e:
            logger.error(f"Failed to switch suite family: {e}")
            raise RuntimeError(f"Failed to switch to suite_family {target_family}: {e}")

    def reset(self, go_home: bool) -> Response:
        """Resets the environment by going home if requested."""
        self._ensure_initialized()

        if go_home:
            self.execute_action(JSONAction(action_type=NAVIGATE_HOME))

        return Response(status="success", message="Environment reset")

    @backoff.on_exception(
        backoff.expo,
        Exception,
        max_tries=3,
        on_backoff=lambda details: logger.warning(
            f"Retrying get_screenshot after error (attempt {details['tries']}/3)"
        ),
    )
    def get_screenshot(self, wait_to_stabilize: bool = False) -> Image.Image:
        """Gets the current screenshot of the environment."""
        self._ensure_initialized()

        if wait_to_stabilize:
            time.sleep(self.step_wait_time)

        response = requests.get(
            f"{self.base_url}/screenshot",
            params={"device": self.device, "return_b64": True},
        )
        # response.raise_for_status()
        if not response.ok:
            logger.error(f"Failed to get screenshot: {response.text}")
            raise RuntimeError(f"Failed to get screenshot: {response.text}")

        # Convert base64 to numpy array
        image_base64 = response.json()["b64_png"]
        image = self._base64_to_pil(image_base64)

        return image

    def get_observation(self, type="screenshot", wait_to_stabilize: bool = True) -> dict:
        """Gets the current observation of the environment."""
        if type == "screenshot":
            return {
                "screenshot": self.get_screenshot(wait_to_stabilize=wait_to_stabilize),
                "accessibility_tree": None,
            }
        elif type == "accessibility_tree":
            raise ValueError("Accessibility tree is not supported yet")
        elif type == "screenshot_and_accessibility_tree":
            raise ValueError("Screenshot and accessibility tree is not supported yet")
        else:
            raise ValueError(f"Unsupported observation type: {type}")

    def execute_action(self, action: JSONAction) -> Observation:
        """Executes an action in the environment."""
        self._ensure_initialized()

        logger.debug(f"Executing action: {action.model_dump_json(exclude_none=True)}")

        # Send JSONAction directly to server
        step_data = {
            "device": self.device,
            "action": action.model_dump(),
        }

        response = requests.post(f"{self.base_url}/step", json=step_data)
        logger.debug(f"""execute_action response: {{
            "status": {response.status_code},
            "message": {response.text},
        }}""")

        res = self.get_screenshot(wait_to_stabilize=True)
        ask_user_response = None
        if action.action_type == "ask_user" and response.text is not None:
            message = json.loads(response.text)
            ask_user_response = message.get("result", "")
            logger.debug(f"ask_user_response: {ask_user_response}")

        return Observation(
            screenshot=res,
            ask_user_response=ask_user_response,
        )

    def get_suite_task_list(self, enable_mcp: bool = False, enable_user_interaction: bool = False) -> list[str]:
        """Gets the list of tasks in the suite.
        
        Args:
            enable_mcp: If True, include agent-mcp tasks. Default False excludes them.
            enable_user_interaction: If True, include agent-user-interaction tasks. Default False excludes them.
        
        Returns:
            List of task names filtered by the specified criteria.
            By default (both False), returns only GUI-only tasks.
        """
        self._ensure_initialized()

        response = requests.get(f"{self.base_url}/task/list")
        response.raise_for_status()
        task_list = response.json()
        
        # Filter tasks based on tags
        filtered_tasks = []
        gui_only = []
        for task in task_list:
            tags = task.get("tags", [])
            # Skip agent-mcp tasks if not enabled
            if not enable_mcp and "agent-mcp" in tags:
                continue
            # Skip agent-user-interaction tasks if not enabled
            if not enable_user_interaction and "agent-user-interaction" in tags:
                continue
            filtered_tasks.append(task["name"])
        return filtered_tasks

    def get_suite_task_length(self, task_type: str) -> int:
        """Gets the length of the suite of tasks."""
        # Return 1 since we're simulating single task execution
        return 1

    def reinitialize_suite(
        self,
        n_task_combinations: int = 1,
        seed: int = 42,
        task_family: str = "mobile_world",
    ) -> Response:
        """Reinitializes the suite of tasks."""
        # For the new server, this is just a no-op
        return Response(status="success", message="Suite reinitialized")

    def initialize_task(self, task_name: str) -> Observation:
        """Initializes the task in the environment."""
        self._ensure_initialized()

        try:
            init_data = {"task_name": task_name, "req_device": self.device}
            response = requests.post(f"{self.base_url}/task/init", json=init_data, timeout=300)
            response.raise_for_status()

            self._current_task_type = task_name

            logger.debug(f"initialize_task response: Task {task_name} initialized")
            res = self.get_screenshot(wait_to_stabilize=True)
            return Observation(
                screenshot=res,
                ask_user_response=None,
            )
        except Exception as e:
            logger.error(f"Failed to initialize task {task_name}: {e}")
            raise RuntimeError(f"Failed to initialize task {task_name}: {e}")

    def tear_down_task(self, task_type: str) -> Response:
        """Tears down the task in the environment."""
        self._ensure_initialized()

        try:
            tear_down_data = {"task_name": task_type, "req_device": self.device}
            response = requests.post(f"{self.base_url}/task/tear_down", json=tear_down_data)
            response.raise_for_status()

            self._current_task_type = None
            return Response(status="success", message=f"Task {task_type} torn down")
        except Exception as e:
            logger.error(f"Failed to tear down task {task_type}: {e}")
            return Response(
                status="error",
                message=f"Failed to tear down task {task_type}: {str(e)}",
            )

    def get_task_score(self, task_type: str) -> tuple[float, str]:
        """Gets the score of the current task."""
        self._ensure_initialized()

        try:
            response = requests.get(
                f"{self.base_url}/task/eval",
                json={"task_name": task_type, "req_device": self.device},
            )
            response.raise_for_status()
            result = response.json()
            score = float(result.get("score", 0.0))
            reason = result.get("reason", f"No reason provided for {task_type}")
            return score, reason
        except Exception:
            logger.exception(f"Failed to get task score for {task_type}")
            raise RuntimeError(f"Failed to get task score for {task_type}")

    def get_task_goal(self, task_type: str) -> str:
        """Gets the goal of the current task."""
        self._ensure_initialized()

        response = requests.get(f"{self.base_url}/task/goal", params={"task_name": task_type})
        response.raise_for_status()
        return response.json()

    def get_task_metadata(self, task_type: str) -> dict:
        """Gets the metadata of the current task."""
        self._ensure_initialized()

        response = requests.get(f"{self.base_url}/task/metadata", params={"task_name": task_type})
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        """Closes the environment."""
        # The new server doesn't have a close endpoint, so this is a no-op
        pass

    def health(self) -> bool:
        """Checks the health of the environment."""
        try:
            response = requests.get(f"{self.base_url}/health")
            response.raise_for_status()
            result = response.json()
            return result.get("ok", False)
        except Exception as e:
            print(f"Environment is not healthy: {e}")
            return False

    def get_task_complexity(self, task_type: str) -> float:
        """Gets the complexity of the current task."""
        self._ensure_initialized()

        response = requests.get(f"{self.base_url}/task/complexity", params={"task_name": task_type})
        response.raise_for_status()
        return float(response.json())

    def _base64_to_pil(self, base64_str: str) -> Image.Image:
        """Convert base64 string to numpy array."""
        # Remove data URL prefix if present
        if "," in base64_str:
            base64_str = base64_str.split(",")[-1]

        image_data = base64.b64decode(base64_str)
        image = Image.open(BytesIO(image_data))
        return image

    def get_task_list(self) -> list[str]:
        """Get the list of tasks."""
        response = requests.get(f"{self.base_url}/task/list")
        response.raise_for_status()
        return response.json()


class AndroidMCPEnvClient(AndroidEnvClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # initialize the MCP client
        logger.debug("initializing the MCP client")
        mcp_client = init_mcp_clients()
        self.tools = []
        self.tools = mcp_client.list_tools_sync()
        self.complete_tool_set = copy.deepcopy(self.tools)
        self.tool_map = {tool["name"]: mcp_client for tool in self.tools}

        logger.debug(f"loaded {len(self.tools)} tools: {[tool['name'] for tool in self.tools]}")

    def reset_tools(self, filters: list[str] = None, task_type=None):
        is_not_mcp_task = True
        if task_type is not None:
            metadata = self.get_task_metadata(task_type=task_type)
            filters = []  # we should set empty tools if task has no mcp tag
            if "agent-mcp" in metadata["tags"]:
                is_not_mcp_task = False
                for app in metadata.get("apps", []):
                    if "MCP" in app:
                        filters.append(app.split("-")[-1])
            logger.debug(f"setting filters for task {task_type}: {filters}")

        if filters is not None:
            self.tools = [
                tool
                for tool in self.complete_tool_set
                if any(f.lower() in tool["name"].lower() for f in filters)
            ]
            assert len(self.tools) > 0 or is_not_mcp_task, f"No tools found for task {task_type}"
            logger.debug(f"reset tools: {self.tools}")

    def _truncate_tool_call(self, tool_call: dict) -> dict:
        """Truncate the tool call to 1000 characters."""
        if tool_call is not None:
            if "text" in tool_call and tool_call["text"].startswith("<!DOCTYPE html>"):
                tool_call["text"] = markdownify(tool_call["text"])
        return tool_call

    def execute_action(self, action: JSONAction) -> Observation:
        if action.action_type == MCP:
            action_name = action.action_name
            action_args = action.action_json
            client = self.tool_map[action_name]
            result = client.call_tool_sync(action_name, action_args)
            result = self._truncate_tool_call(result)

            res = self.get_screenshot(wait_to_stabilize=True)
            return Observation(
                screenshot=res,
                ask_user_response=None,
                tool_call=result,
            )
        else:
            return super().execute_action(action)


def parse_result_file(result_file: str) -> tuple[float, str | None]:
    """Parse the result file."""
    with open(result_file) as f:
        lines = f.readlines()
        if len(lines) > 0 and "score:" in lines[0]:
            score = float(lines[0].split("score:")[1].strip())
        else:
            score = None

        if len(lines) > 1:
            reason = lines[1].strip()
        else:
            reason = None
        return score, reason


def scan_finished_tasks(
    log_file_root: str, task_list: list[str] = None
) -> tuple[list[str], list[float]]:
    """Scan for finished tasks in log directory."""
    if not os.path.exists(log_file_root):
        return [], []

    dirs = [
        d
        for d in os.listdir(log_file_root)
        if os.path.exists(os.path.join(log_file_root, d, SCORE_FILE_NAME))
        and "backup" not in d
        and (task_list is None or d in task_list)
    ]

    result_files = [os.path.join(log_file_root, d, SCORE_FILE_NAME) for d in dirs]
    results = []
    for result_file in result_files:
        score, _ = parse_result_file(result_file)
        results.append(score)
    return dirs, results
