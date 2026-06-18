"""MemGUI Agent with ConAct design for explicit UI memory and proactive context folding.

This agent implements the ConAct approach where the model emits both UI
actions and context actions (history folding or UI memory operations). Key features:

1. Folded Action History: Compressed records of past actions at different
   granularities (step-level vs span-level).

2. Folding Directive: Agent outputs a folding instruction at each step to
   control how its history is compressed.

3. Two Folding Modes:
   - Step-level Distillation: Distill a single step into a compact record
   - Span-level Abstraction: Abstract a multi-step span into one reusable summary

4. Folded UI State (Memory): Agent can explicitly store, update, and delete
   key information extracted from UI.

This approach prevents context saturation while maintaining important information.
"""

import json
import re
import traceback
from typing import Any

from loguru import logger

from mobile_world.agents.base import MCPAgent
from mobile_world.agents.utils.agent_mapping import QWENVL2AW_ACTION_MAP
from mobile_world.agents.utils.helpers import pil_to_base64
from mobile_world.agents.utils.prompts.memgui import MEMGUI_SYSTEM_PROMPT, MEMGUI_USER_TEMPLATE
from mobile_world.runtime.utils.models import ENV_FAIL, WAIT, JSONAction

# Coordinate scale used by MemGUI agent (0-1000)
MEMGUI_COORD_SCALE = 1000

# Memory-only action types that do not map to env actions
MEMORY_ACTION_TYPES = {"memory_add", "memory_update", "memory_delete"}


def _extract_tag(text: str, tag: str) -> str:
    """Extract content from an XML-like tag in the model output."""
    match = re.search(
        rf"<{tag}>\s*(.*?)\s*</{tag}>",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _extract_tool_call(text: str) -> dict | None:
    """Extract and parse the <tool_call> JSON block from model output."""
    match = re.search(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse tool_call JSON: {e}")
        return None


def _extract_folding_directive(text: str, current_step: int) -> dict | None:
    """Extract the <folding> directive from model output.

    Returns a dict with 'range' and 'summary' keys, or None if absent.
    """
    match = re.search(r"<folding>\s*(.*?)\s*</folding>", text, re.DOTALL | re.IGNORECASE)
    if not match:
        return None

    folding_text = match.group(1).strip()
    if folding_text.startswith("{"):
        try:
            return json.loads(folding_text)
        except json.JSONDecodeError:
            pass

    # Fallback: treat the whole text as the summary for the current step
    return {
        "range": [current_step, current_step],
        "summary": folding_text,
    }


def parse_memgui_response(
    text: str,
    image_height: int,
    image_width: int,
    current_step: int,
) -> dict:
    """Parse the full MemGUI model response into structured components.

    Returns a dict with keys:
        thinking, folding_directive, action_json, action_name,
        ui_observation, action_intent, memory_args (or None)
    """
    thinking = _extract_tag(text, "thinking")
    ui_observation = _extract_tag(text, "ui_observation")
    action_intent = _extract_tag(text, "action_intent")
    folding_directive = _extract_folding_directive(text, current_step)

    tool_call = _extract_tool_call(text)
    if tool_call is None:
        raise ValueError("No <tool_call> block found in model output")

    action_name = tool_call.get("name", "mobile_use")
    action_args = tool_call.get("arguments", {})
    action_type = action_args.get("action")

    memory_args = None
    if action_type in MEMORY_ACTION_TYPES:
        # Memory operation: extract memory-specific fields
        memory_args = {
            "operation": action_type.replace("memory_", ""),
            "memory_id": action_args.get("memory_id"),
            "description": action_args.get("description", ""),
            "content": action_args.get("content"),
        }

    # Normalise coordinates from 0-1000 scale to 0.0-1.0 relative coords,
    # then multiply by image dimensions when building the JSONAction.
    if "coordinate" in action_args:
        coords = action_args["coordinate"]
        if len(coords) == 2:
            action_args["coordinate"] = [
                coords[0] / MEMGUI_COORD_SCALE,
                coords[1] / MEMGUI_COORD_SCALE,
            ]

    if "coordinate2" in action_args:
        coords2 = action_args["coordinate2"]
        if len(coords2) == 2:
            action_args["coordinate2"] = [
                coords2[0] / MEMGUI_COORD_SCALE,
                coords2[1] / MEMGUI_COORD_SCALE,
            ]

    return {
        "thinking": thinking,
        "folding_directive": folding_directive,
        "action_json": action_args,
        "action_name": action_name,
        "ui_observation": ui_observation,
        "action_intent": action_intent,
        "memory_args": memory_args,
    }


def build_json_action(parsed: dict, image_height: int, image_width: int) -> JSONAction:
    """Convert parsed MemGUI action_json to a MobileWorld JSONAction.

    Coordinate values in action_json are expected to be in the [0, 1] range
    (already normalised from 0-1000 by parse_memgui_response).
    """
    action_json = parsed["action_json"]
    action_type = action_json.get("action")

    if action_type == "click":
        coord = action_json.get("coordinate", [None, None])
        x = round(float(coord[0]) * image_width)
        y = round(float(coord[1]) * image_height)
        return JSONAction(action_type=QWENVL2AW_ACTION_MAP["click"], x=x, y=y)

    elif action_type == "long_press":
        coord = action_json.get("coordinate", [None, None])
        x = round(float(coord[0]) * image_width)
        y = round(float(coord[1]) * image_height)
        return JSONAction(action_type=QWENVL2AW_ACTION_MAP["long_press"], x=x, y=y)

    elif action_type == "swipe":
        coord = action_json.get("coordinate", [None, None])
        coord2 = action_json.get("coordinate2", [None, None])
        if coord and coord2 and coord[0] is not None and coord2[0] is not None:
            start_x = round(float(coord[0]) * image_width)
            start_y = round(float(coord[1]) * image_height)
            end_x = round(float(coord2[0]) * image_width)
            end_y = round(float(coord2[1]) * image_height)
            return JSONAction(
                action_type=QWENVL2AW_ACTION_MAP["swipe"],
                start_x=start_x,
                start_y=start_y,
                end_x=end_x,
                end_y=end_y,
            )
        raise ValueError(f"swipe action missing coordinates: {action_json}")

    elif action_type == "type":
        return JSONAction(
            action_type=QWENVL2AW_ACTION_MAP["type"],
            text=action_json.get("text", ""),
        )

    elif action_type == "answer":
        return JSONAction(
            action_type=QWENVL2AW_ACTION_MAP["answer"],
            text=action_json.get("text", ""),
        )

    elif action_type == "system_button":
        button = action_json.get("button", "").lower()
        button_map = {
            "back": QWENVL2AW_ACTION_MAP["back"],
            "home": QWENVL2AW_ACTION_MAP["home"],
            "enter": QWENVL2AW_ACTION_MAP["enter"],
        }
        mapped = button_map.get(button)
        if mapped is None:
            raise ValueError(f"Unsupported system_button: {button}")
        return JSONAction(action_type=mapped)

    elif action_type == "wait":
        return JSONAction(action_type=QWENVL2AW_ACTION_MAP["wait"])

    elif action_type == "terminate":
        status = action_json.get("status", "success")
        return JSONAction(
            action_type=QWENVL2AW_ACTION_MAP["terminate"],
            text=status,
        )

    elif action_type in MEMORY_ACTION_TYPES:
        # Memory operations do not correspond to env actions; return a wait
        return JSONAction(action_type=WAIT)

    raise ValueError(f"Unknown action type: {action_type}")


class MemGUIAgent(MCPAgent):
    """MemGUI Agent with ConAct design for MobileWorld.

    Adapts MemGUIAgent26010302 from the reference MemGUI-Rollout codebase to
    the MobileWorld agent interface (MCPAgent.predict).

    State maintained across steps:
        current_step: int
        state_summaries: list of (start_step, end_step, summary_text) — Folded Action History
        latest_interaction: dict with details of the most recent step — Recent Step Record
        memory_state: dict mapping memory_id -> {description, content} — Folded UI State
    """

    def __init__(
        self,
        model_name: str,
        llm_base_url: str,
        api_key: str = "empty",
        runtime_conf: dict | None = None,
        *args: Any,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self.model_name = model_name
        self.llm_base_url = llm_base_url
        self.runtime_conf = runtime_conf or {"temperature": 0.0}
        self.build_openai_client(self.llm_base_url, api_key)

        # Folding state
        self.current_step: int = 0
        self.state_summaries: list[tuple[int, int, str]] = []
        self.latest_interaction: dict | None = None
        self.memory_state: dict[str, dict] = {}

        # History for logging / compatibility
        self.history_responses: list[str] = []
        self.thoughts: list[str] = []
        self.ui_observations: list[str] = []
        self.action_intents: list[str] = []

        # Folding statistics
        self.folding_stats = {
            "step_level_distillations": 0,
            "span_level_abstractions": 0,
            "total_steps_folded": 0,
        }

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    def _format_state_summaries(self) -> str:
        if not self.state_summaries:
            return "  (no previous steps)"
        return "\n".join(f"  {summary}" for _, _, summary in self.state_summaries)

    def _format_latest_interaction(self) -> str:
        if not self.latest_interaction:
            return "  (no previous interaction)"
        li = self.latest_interaction
        parts = [f"  Step {li['step']}:"]
        if li.get("ui_observation"):
            parts.append(f"    UI Observation: {li['ui_observation']}")
        if li.get("action_intent"):
            parts.append(f"    Action Intent: {li['action_intent']}")
        if li.get("action_summary"):
            parts.append(f"    Action Taken: {li['action_summary']}")
        return "\n".join(parts)

    def _format_memory_state(self) -> str:
        if not self.memory_state:
            return "  (empty)"
        entries = []
        for mem_id, mem_data in self.memory_state.items():
            if isinstance(mem_data, dict):
                entries.append(
                    f"  [{mem_id}]\n"
                    f"    Description: {mem_data.get('description', '')}\n"
                    f"    Content: {mem_data.get('content', '')}"
                )
            else:
                entries.append(f"  [{mem_id}]: {mem_data}")
        return "\n".join(entries)

    # ------------------------------------------------------------------
    # Folding
    # ------------------------------------------------------------------

    def _apply_folding_directive(self, directive: dict) -> None:
        fold_range = directive.get("range", [])
        summary = directive.get("summary", "")
        if len(fold_range) != 2 or not summary:
            logger.warning(f"Invalid folding directive: {directive}")
            return

        start_step, end_step = int(fold_range[0]), int(fold_range[1])
        if start_step > end_step or end_step > self.current_step:
            logger.warning(f"Invalid folding range: [{start_step}, {end_step}]")
            return

        if start_step == end_step:
            self.folding_stats["step_level_distillations"] += 1
            fold_type = "Step-level Distillation"
        else:
            self.folding_stats["span_level_abstractions"] += 1
            fold_type = "Span-level Abstraction"

        self.folding_stats["total_steps_folded"] += end_step - start_step + 1
        logger.info(f"[FOLD] {fold_type}: Steps [{start_step}-{end_step}] -> \"{summary}\"")

        # Replace any overlapping summaries with the new one
        self.state_summaries = [
            (s, e, t)
            for (s, e, t) in self.state_summaries
            if e < start_step or s > end_step
        ]
        self.state_summaries.append((start_step, end_step, summary))
        self.state_summaries.sort(key=lambda x: x[0])

    # ------------------------------------------------------------------
    # Memory operations
    # ------------------------------------------------------------------

    def _execute_memory_operation(self, memory_args: dict) -> str:
        operation = memory_args.get("operation", "none")
        memory_id = memory_args.get("memory_id")
        description = memory_args.get("description", "")
        content = memory_args.get("content")

        if operation == "add":
            if memory_id and content:
                self.memory_state[memory_id] = {"description": description, "content": content}
                preview = content[:50] + "..." if len(content) > 50 else content
                return f"Added memory [{memory_id}]: {description} | {preview}"
            return "Failed to add memory: missing memory_id or content"

        elif operation == "update":
            if memory_id and content:
                old = self.memory_state.get(memory_id, {})
                self.memory_state[memory_id] = {
                    "description": description or old.get("description", ""),
                    "content": content,
                }
                return f"Updated memory [{memory_id}]"
            return "Failed to update memory: missing memory_id or content"

        elif operation == "delete":
            if memory_id and memory_id in self.memory_state:
                self.memory_state.pop(memory_id)
                return f"Deleted memory [{memory_id}]"
            return f"Failed to delete memory [{memory_id}]: not found"

        return "No memory operation performed"

    # ------------------------------------------------------------------
    # predict
    # ------------------------------------------------------------------

    def predict(self, observation: dict[str, Any]) -> tuple[str, JSONAction]:
        """Predict the next action based on current screenshot and folded context."""
        self.current_step += 1

        screenshot = observation["screenshot"]
        encoded_string = pil_to_base64(screenshot)
        image_width, image_height = screenshot.width, screenshot.height

        # Build user prompt
        folding_instruction = (
            "Skip <folding> for the first step"
            if self.current_step == 1
            else "Output <folding> to compress your previous step(s)"
        )
        user_content = MEMGUI_USER_TEMPLATE.format(
            instruction=self.instruction,
            state_summaries=self._format_state_summaries(),
            latest_interaction=self._format_latest_interaction(),
            memory_state=self._format_memory_state(),
            folding_instruction=folding_instruction,
        )

        messages = [
            {"role": "system", "content": [{"type": "text", "text": MEMGUI_SYSTEM_PROMPT}]},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_content},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded_string}"},
                    },
                ],
            },
        ]

        try_times = 3
        parsed_response = None
        prediction = None

        while try_times > 0:
            prediction = self.openai_chat_completions_create(
                model=self.model_name,
                messages=messages,
                retry_times=3,
                **self.runtime_conf,
            )

            if prediction is None:
                raise RuntimeError("Error when fetching response from model")

            try:
                parsed_response = parse_memgui_response(
                    prediction,
                    image_height=image_height,
                    image_width=image_width,
                    current_step=self.current_step,
                )
                logger.info(f"[MemGUI Step {self.current_step}] Parsed response OK")
                break
            except Exception:
                try_times -= 1
                logger.error(f"Error parsing model response (remaining retries: {try_times})")
                logger.error(traceback.format_exc())
                prediction = None

        if parsed_response is None or prediction is None:
            logger.error("Failed to parse model response after maximum retries")
            return "memgui parse error after multiple retries", JSONAction(action_type=ENV_FAIL)

        # ------------------------------------------------------------------
        # Apply folding directive
        # ------------------------------------------------------------------
        folding_directive = parsed_response["folding_directive"]
        if self.current_step > 1:
            if folding_directive:
                self._apply_folding_directive(folding_directive)
            else:
                # Auto-fold last step if no directive provided
                auto_directive = {
                    "range": [self.current_step - 1, self.current_step - 1],
                    "summary": (
                        f"[Step {self.current_step - 1}] "
                        f"{parsed_response['action_intent'] or 'Action performed'}"
                    ),
                }
                self._apply_folding_directive(auto_directive)

        # ------------------------------------------------------------------
        # Handle memory operations
        # ------------------------------------------------------------------
        memory_args = parsed_response.get("memory_args")
        action_summary = ""

        if memory_args:
            result = self._execute_memory_operation(memory_args)
            logger.info(f"[MemGUI Memory] {result}")
            action_summary = f"Memory: {result}"
            json_action = JSONAction(action_type=WAIT)
        else:
            # Build env action
            try:
                json_action = build_json_action(parsed_response, image_height, image_width)
                action_summary = json_action.action_type or "unknown"
            except Exception as e:
                logger.error(f"Failed to build JSONAction: {e}")
                json_action = JSONAction(action_type=ENV_FAIL)
                action_summary = f"build_action_error: {e}"

        # ------------------------------------------------------------------
        # Update agent state for next step
        # ------------------------------------------------------------------
        self.latest_interaction = {
            "step": self.current_step,
            "ui_observation": parsed_response["ui_observation"],
            "action_intent": parsed_response["action_intent"],
            "action_summary": action_summary,
        }

        self.history_responses.append(prediction)
        self.thoughts.append(parsed_response["thinking"])
        self.ui_observations.append(parsed_response["ui_observation"])
        self.action_intents.append(parsed_response["action_intent"])

        logger.info(
            f"[MemGUI Step {self.current_step}] action={json_action.action_type} "
            f"summaries={len(self.state_summaries)} memory_keys={list(self.memory_state.keys())}"
        )

        return prediction, json_action

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset agent state for the next task."""
        self.current_step = 0
        self.state_summaries = []
        self.latest_interaction = None
        self.memory_state = {}
        self.history_responses = []
        self.thoughts = []
        self.ui_observations = []
        self.action_intents = []
        self.folding_stats = {
            "step_level_distillations": 0,
            "span_level_abstractions": 0,
            "total_steps_folded": 0,
        }
