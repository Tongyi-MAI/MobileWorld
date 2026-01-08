# Mobile World Codebase Guide for LLM Code Agents

## Overview

**Mobile World** is a comprehensive benchmark platform for evaluating autonomous mobile GUI agents. It provides 201 tasks across 20 applications, featuring:
- Long-horizon, cross-app workflows
- Agent-User Interactive tasks
- MCP (Model Context Protocol) augmented tasks
- Docker-based Android emulator environments

---

## Project Structure

```
MobileWorld/
├── src/mobile_world/          # Main source code
│   ├── agents/                # Agent implementations
│   ├── core/                  # CLI, server, runner
│   ├── runtime/               # Android controller, client, MCP
│   └── tasks/                 # Task definitions and registry
├── docker/                    # Docker configuration files
├── resources/                 # App resources (mail, mall, mastodon)
├── third-party/android_world/ # Android World integration
├── docs/                      # Documentation
└── site/                      # Web-based visualization
```

---

## Core Architecture

### 1. Entry Point: CLI (`src/mobile_world/core/cli.py`)

The CLI is the main interface, accessible via `mw` or `mobile-world` commands.

**Key Commands:**
| Command | Description |
|---------|-------------|
| `mw env check` | Check Docker/KVM prerequisites |
| `mw env run --count N` | Launch N containerized Android environments |
| `mw eval --agent_type <type> --task ALL` | Run benchmark evaluation |
| `mw test --task <TaskName>` | Test a single task |
| `mw logs view --log_dir <dir>` | View task trajectories |
| `mw info task` | List all available tasks |
| `mw info agent` | List available agents |

**Subcommand modules:** Located in `src/mobile_world/core/subcommands/`
- `eval.py` - Benchmark evaluation
- `test.py` - Single task testing
- `env.py` - Docker environment management
- `logs.py` - Log viewing and export
- `info.py` - Information display
- `device.py` - Device viewer
- `server.py` - Backend API server

---

### 2. Agent System (`src/mobile_world/agents/`)

#### Base Agent Classes (`base.py`)

```python
class BaseAgent(ABC):
    """Abstract base class for all mobile automation agents."""
    
    def initialize(self, instruction: str) -> bool:
        """Initialize agent with task goal."""
    
    @abstractmethod
    def predict(self, observation: dict[str, Any]) -> tuple[str, JSONAction]:
        """Generate next action from observation (screenshot, tool_call, ask_user_response)."""
    
    def done(self) -> None:
        """Finalize agent for current task."""
    
    def reset(self) -> None:
        """Reset agent state for next task."""

class MCPAgent(BaseAgent):
    """Agent with MCP (Model Context Protocol) tool support."""
    
    def __init__(self, tools: list[dict], *args, **kwargs):
        self.tools = tools  # Available MCP tools
    
    def reset_tools(self, tools: list[dict]) -> None:
        """Reset available tools."""
```

#### Agent Registry (`registry.py`)

**Built-in agents:**
- `qwen3vl` - Qwen3 Vision-Language agent with MCP support
- `planner_executor` - Planning + execution agent architecture

**Creating custom agents:**
```python
# Custom agents can be loaded from any Python file:
mw eval --agent_type /path/to/custom_agent.py ...
```

#### Qwen3VL Agent Implementation (`implementations/qwen3vl.py`)

Key functionality:
- Uses OpenAI-compatible API for vision-language model
- Parses structured responses with `Thought:` and `Action:` tags
- Converts model outputs to `JSONAction` format
- Supports coordinate-based actions (click, swipe, etc.)
- Handles MCP tool calls and ask_user interactions

**Action parsing flow:**
1. Model outputs: `Thought: ... Action: "<action_name>" <tool_call>{"name": ..., "arguments": ...}</tool_call>`
2. `parse_tagged_text()` extracts thinking, conclusion, and tool_call
3. `parse_action_to_structure_output()` normalizes coordinates
4. `parsing_response_to_andoid_world_env_action()` converts to `JSONAction`

---

### 3. Task System (`src/mobile_world/tasks/`)

#### Base Task Class (`base.py`)

```python
class BaseTask(ABC):
    """Abstract base class for all tasks."""
    
    @property
    @abstractmethod
    def app_names(self) -> set[str]:
        """Apps the agent interacts with during the task."""
    
    @property
    @abstractmethod
    def goal(self) -> str:
        """The natural language goal/instruction for the task."""
    
    @property
    def task_tags(self) -> set[str]:
        """Tags like 'agent-mcp', 'lang-en', 'lang-cn'."""
    
    @property
    def snapshot_tag(self) -> str | None:
        """AVD snapshot to load before task (default: 'init_state')."""
    
    def initialize_task(self, controller: AndroidController) -> bool:
        """Initialize task - loads snapshot, syncs time, runs hooks."""
    
    def initialize_task_hook(self, controller: AndroidController) -> bool:
        """Custom initialization logic (override this)."""
    
    def initialize_user_agent_hook(self, controller: AndroidController) -> bool:
        """Setup user agent for ask_user interactions."""
    
    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        """Evaluate task success. Returns score (0.0-1.0) and optional reason."""
    
    async def is_successful_async(self, controller: AndroidController) -> float | tuple[float, str]:
        """Async version of is_successful (for MCP tasks)."""
    
    def tear_down(self, controller: AndroidController) -> None:
        """Cleanup after task completion."""
```

#### Task Registry (`registry.py`)

```python
class TaskRegistry:
    """Auto-discovers and registers all tasks from definitions directory."""
    
    def __init__(self, task_set_path: str | None = None):
        # Scans src/mobile_world/tasks/definitions/ for BaseTask subclasses
    
    def get_task(self, task_name: str) -> BaseTask
    def list_tasks(self) -> list[str]
    def has_task(self, task_name: str) -> bool
```

#### Task Categories (in `tasks/definitions/`)

| Directory | Description | Example Tasks |
|-----------|-------------|---------------|
| `calendar/` | Calendar event management | AddBusinessTripWithCafeTask |
| `chrome/` | Browser tasks | Web search, navigation |
| `gmail/` | Email operations | Compose, read, search |
| `mall/` | E-commerce tasks | Shopping, checkout |
| `map/` | Map/navigation tasks | CheckDistanceMcpTask |
| `mastodon/` | Social media tasks | MastodonReportTask |
| `messages/` | SMS/messaging | Send messages |
| `native/` | System apps | Alarms, camera, files |
| `settings/` | Device settings | WiFi, display |
| `work/` | Productivity tasks | Mattermost integration |

#### Task Tags

- `agent-mcp` - Requires MCP tools
- `lang-en` - English language task
- `lang-cn` - Chinese language task

---

### 4. Runtime System (`src/mobile_world/runtime/`)

#### Android Controller (`controller.py`)

Low-level Android device control via ADB:

```python
class AndroidController:
    def __init__(self, device="emulator-5554"):
        self.device = device
        self.width, self.height = self.get_device_size()
    
    # Screenshots & UI
    def get_screenshot(self, prefix, save_dir) -> AdbResponse
    def get_xml(self, prefix, save_dir)  # UI automator dump
    
    # Basic actions
    def tap(self, x: int, y: int) -> AdbResponse
    def double_tap(self, x: int, y: int) -> AdbResponse
    def long_press(self, x: int, y: int, duration: int = 1000) -> AdbResponse
    def swipe(self, x, y, direction: str) -> AdbResponse
    def drag(self, start_x, start_y, end_x, end_y) -> AdbResponse
    def text(self, input_str: str) -> AdbResponse
    
    # Navigation
    def back() -> AdbResponse
    def home() -> AdbResponse
    def enter() -> AdbResponse
    def app_switch() -> AdbResponse
    def launch_app(self, app_name: str) -> AdbResponse
    
    # Snapshot management
    def list_snapshots() -> list[str]
    def create_snapshot(self, tag) -> str
    def load_snapshot(self, tag) -> bool
    def delete_snapshot(self, tag) -> bool
    
    # User interaction
    def answer(self, answer_str: str) -> None  # For answer action
    def ask_user(self, agent_question: str) -> str  # Simulated user response
    
    # File operations
    def push_file(self, local_path, remote_path) -> AdbResponse
    def pull_file(self, remote_path, local_path) -> AdbResponse
    
    # Health check
    def check_health(self, try_times=0) -> bool
```

#### Client (`client.py`)

HTTP client for communicating with the backend server:

```python
class AndroidEnvClient:
    """Client for the FastAPI Android environment server."""
    
    def __init__(self, url="http://localhost:8000", device="emulator-5554"):
        self._task_registry = TaskRegistry()
    
    def get_screenshot(self, wait_to_stabilize=False) -> Image
    def execute_action(self, action: JSONAction) -> Observation
    
    def initialize_task(self, task_name: str) -> Observation
    def tear_down_task(self, task_type: str) -> Response
    def get_task_score(self, task_type: str) -> tuple[float, str]
    def get_task_goal(self, task_type: str) -> str
    def get_suite_task_list(self, enable_mcp=False) -> list[str]
    
    def switch_suite_family(self, target_family: str) -> dict

class AndroidMCPEnvClient(AndroidEnvClient):
    """Client with MCP tool support."""
    
    def __init__(self, *args, **kwargs):
        self.tools = init_mcp_clients().list_tools_sync()
        self.tool_map = {tool["name"]: client for tool in self.tools}
    
    def reset_tools(self, filters=None, task_type=None)
    def execute_action(self, action: JSONAction) -> Observation
        # Handles MCP action type by calling tool_map
```

#### MCP Server (`mcp_server.py`)

Integration with Model Context Protocol services:

```python
MCP_CONFIG = {
    "mcpServers": {
        "amap": {...},      # Map services (Amap)
        "gitHub": {...},    # GitHub operations
        "jina": {...},      # Web search/scraping
        "stockstar": {...}, # Stock information
        "arXiv": {...},     # Academic paper search
    }
}

class SyncMCPClient:
    """Synchronous wrapper for async MCP client."""
    
    def list_tools_sync() -> list[dict]
    def call_tool_sync(self, name: str, arguments: dict) -> dict
```

---

### 5. Action System (`runtime/utils/models.py`)

#### Action Types

```python
# Action type constants
ANSWER = "answer"           # Return answer to task
CLICK = "click"             # Tap at coordinates
DOUBLE_TAP = "double_tap"   # Double tap
INPUT_TEXT = "input_text"   # Type text
KEYBOARD_ENTER = "keyboard_enter"
LONG_PRESS = "long_press"
NAVIGATE_BACK = "navigate_back"
NAVIGATE_HOME = "navigate_home"
OPEN_APP = "open_app"
SCROLL = "scroll"           # Scroll in direction
SWIPE = "swipe"             # Swipe between points
DRAG = "drag"               # Drag from start to end
WAIT = "wait"               # Wait for screen update
ASK_USER = "ask_user"       # Query simulated user
MCP = "mcp"                 # Call MCP tool
FINISHED = "finished"       # Task complete
```

#### JSONAction Model

```python
class JSONAction(BaseModel):
    action_type: str | None
    x: int | None              # For click/tap
    y: int | None
    text: str | None           # For input_text, answer, ask_user
    direction: str | None      # For scroll: up/down/left/right
    app_name: str | None       # For open_app
    start_x/start_y: int | None  # For drag/swipe
    end_x/end_y: int | None
    action_name: str | None    # For MCP tool name
    action_json: dict | None   # For MCP tool arguments
```

#### Observation Model

```python
class Observation(BaseModel):
    screenshot: Image.Image    # Current screen
    ask_user_response: str | None  # Response from simulated user
    tool_call: dict | None     # Result from MCP tool call
```

---

### 6. Execution Flow (`core/runner.py`)

```python
def run_agent_with_evaluation(
    agent_type: str,
    model_name: str,
    llm_base_url: str,
    log_file_root: str,
    tasks: list[str],
    max_step: int,
    enable_mcp: bool = False,
    ...
) -> list[dict]:
    """
    Main evaluation loop:
    1. Auto-discover Docker containers or use provided URLs
    2. Initialize environments (AndroidEnvClient or AndroidMCPEnvClient)
    3. Get task list from first environment
    4. Execute tasks in parallel using joblib
    5. Return results with scores
    """

def _execute_single_task(
    env: AndroidEnvClient,
    agent: BaseAgent,
    task_name: str,
    max_step: int,
    ...
) -> tuple[int, float]:
    """
    Single task execution:
    1. Get task goal from env
    2. Initialize task (loads snapshot, runs hooks)
    3. Initialize agent with goal
    4. Loop until max_step or terminate:
       - Get observation (screenshot + tool_call + ask_user_response)
       - Agent predicts action
       - Execute action
       - Check for termination actions
    5. Evaluate task success
    6. Tear down task
    """
```

---

### 7. Server API (`core/server.py`)

FastAPI server running inside Docker container:

**Endpoints:**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/init` | POST | Initialize device controller |
| `/screenshot` | GET | Get current screenshot (base64) |
| `/step` | POST | Execute action |
| `/task/init` | POST | Initialize a task |
| `/task/eval` | GET | Evaluate task success |
| `/task/tear_down` | POST | Cleanup task |
| `/task/goal` | GET | Get task goal string |
| `/task/list` | GET | List all available tasks |
| `/task/metadata` | GET | Get task metadata |
| `/health` | GET | Health check |
| `/suite_family/switch` | POST | Switch suite family |

---

### 8. App Helpers (`runtime/app_helpers/`)

Backend integrations for verification:

| Module | Purpose |
|--------|---------|
| `mastodon.py` | Mastodon backend control, user/post queries |
| `mattermost.py` | Mattermost backend control |
| `mall.py` | E-commerce backend, callback handling |
| `mail.py` | Email backend operations |
| `fossify_calendar.py` | Calendar event queries |
| `mcp.py` | MCP service helpers |
| `system.py` | System operations (time sync, etc.) |

---

## Key Data Flow

```
┌─────────────┐    CLI Command     ┌─────────────┐
│   User      │ ─────────────────> │   CLI       │
└─────────────┘                    │ (cli.py)    │
                                   └──────┬──────┘
                                          │
                                          v
┌─────────────────────────────────────────────────────────────┐
│                     Runner (runner.py)                       │
│  - Creates AndroidEnvClient(s)                              │
│  - Creates Agent instance                                    │
│  - Loops: observe -> predict -> execute                     │
└──────────────────────────┬──────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           v               v               v
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Agent        │  │ Client       │  │ MCP Client   │
│ (qwen3vl.py) │  │ (client.py)  │  │ (mcp_server) │
│              │  │              │  │              │
│ predict() ───┼──> execute() ──┼──> call_tool() │
└──────────────┘  └──────┬───────┘  └──────────────┘
                         │
                         v HTTP
┌─────────────────────────────────────────────────────────────┐
│              FastAPI Server (server.py)                      │
│              [Inside Docker Container]                       │
│                         │                                    │
│                         v                                    │
│              ┌──────────────────┐                           │
│              │ AndroidController │                           │
│              │  (controller.py)  │                           │
│              │       │          │                           │
│              │       v ADB      │                           │
│              │ ┌────────────┐   │                           │
│              │ │ Android    │   │                           │
│              │ │ Emulator   │   │                           │
│              │ └────────────┘   │                           │
│              └──────────────────┘                           │
└─────────────────────────────────────────────────────────────┘
```

---

## Creating New Components

### Adding a New Agent

1. Create file in `src/mobile_world/agents/implementations/` or external location
2. Inherit from `BaseAgent` or `MCPAgent`
3. Implement `predict(observation) -> tuple[str, JSONAction]`

```python
from mobile_world.agents.base import MCPAgent
from mobile_world.runtime.utils.models import JSONAction

class MyCustomAgent(MCPAgent):
    def __init__(self, model_name, llm_base_url, api_key, **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name
        # Setup...
    
    def predict(self, observation: dict) -> tuple[str, JSONAction]:
        screenshot = observation["screenshot"]  # PIL Image
        tool_call = observation.get("tool_call")  # Previous MCP result
        ask_user_response = observation.get("ask_user_response")
        
        # Your logic here...
        
        return reasoning_text, JSONAction(
            action_type="click",
            x=100,
            y=200
        )
    
    def reset(self):
        # Clear agent state
        pass
```

### Adding a New Task

1. Create file in appropriate `src/mobile_world/tasks/definitions/<category>/`
2. Inherit from `BaseTask`
3. Define `app_names`, `goal`, and `is_successful()`

```python
from mobile_world.tasks.base import BaseTask
from mobile_world.runtime.controller import AndroidController

class MyNewTask(BaseTask):
    goal = "Complete the specific action..."
    app_names = {"AppName1", "AppName2"}
    task_tags = {"lang-en"}  # Add "agent-mcp" if using MCP
    
    def initialize_task_hook(self, controller: AndroidController) -> bool:
        # Custom setup logic
        return True
    
    def is_successful(self, controller: AndroidController) -> tuple[float, str]:
        # Verification logic
        # Return (1.0, "reason") for success, (0.0, "reason") for failure
        return 1.0, "Task completed successfully"
    
    def tear_down(self, controller: AndroidController) -> bool:
        super().tear_down(controller)
        # Custom cleanup
        return True
```

### Adding MCP-Augmented Tasks

```python
class MyMCPTask(BaseTask):
    goal = "Use MCP tool to..."
    app_names = {"MCP-Amap", "Calendar"}  # MCP-prefixed apps
    task_tags = {"agent-mcp", "lang-en"}
    
    async def is_successful_async(self, controller: AndroidController):
        # Use async for MCP verification
        from mobile_world.runtime.app_helpers import mcp as mcp_helper
        result = await mcp_helper.some_operation()
        # Verify...
```

---

## Configuration

### Environment Variables (`.env`)

```bash
# Required for agent evaluation
API_KEY=your_llm_api_key

# For agent-user interactive tasks
USER_AGENT_API_KEY=your_user_agent_api_key
USER_AGENT_BASE_URL=https://api.openai.com/v1
USER_AGENT_MODEL=gpt-4o-mini

# For MCP-augmented tasks
DASHSCOPE_API_KEY=your_dashscope_key
MODELSCOPE_API_KEY=your_modelscope_key
```

### Docker Configuration

- Image: `ghcr.io/tongyi-mai/mobile_world:latest`
- Container prefix: `mobile_world_env`
- AVD: `Pixel_8_API_34_x86_64`

---

## Debugging Tips

1. **View task trajectories:**
   ```bash
   mw logs view --log_dir traj_logs/
   ```

2. **Test single task:**
   ```bash
   mw test --agent_type qwen3vl --task TaskClassName
   ```

3. **Check available tasks:**
   ```bash
   mw info task
   ```

4. **Check environment health:**
   ```bash
   mw env check
   mw env list
   ```

5. **Enable debug logging:**
   - Logs are written to `traj_logs/<task_name>/thread_*.log`
   - Use `loguru` for structured logging

---

## Dependencies

Key Python packages:
- `fastapi`, `uvicorn` - API server
- `openai` - LLM API client
- `pillow` - Image processing
- `pydantic` - Data validation
- `loguru` - Logging
- `joblib` - Parallel execution
- `mcp`, `fastmcp` - MCP protocol
- `qwen-agent` - Qwen agent utilities

---

## File Naming Conventions

- Task classes: `CamelCaseTask` (e.g., `MastodonReportTask`)
- Task files: `snake_case.py` (e.g., `mastodon_report.py`)
- Agent classes: `CamelCaseAgent` (e.g., `Qwen3VLAgentMCP`)

---

## Common Patterns

### Action Execution Pattern
```python
action = JSONAction(action_type="click", x=100, y=200)
observation = env.execute_action(action)
screenshot = observation.screenshot
```

### Task Verification Pattern
```python
def is_successful(self, controller):
    # Query backend/storage
    data = some_helper.get_data()
    
    # Verify conditions
    if condition_met:
        return 1.0, "Success reason"
    return 0.0, "Failure reason"
```

### MCP Tool Call Pattern
```python
action = JSONAction(
    action_type="mcp",
    action_name="amap_search",
    action_json={"query": "coffee shop", "location": "..."}
)
observation = env.execute_action(action)
result = observation.tool_call
```
