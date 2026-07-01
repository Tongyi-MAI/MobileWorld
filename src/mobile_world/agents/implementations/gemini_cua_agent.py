"""
Gemini Computer Use Agent (CUA) — Google GenAI ``generateContent`` API
with the ``computerUse`` tool targeting mobile/browser/desktop environments.

Uses multi-turn ``contents`` history for conversation state (not the
experimental Interactions API), so it works with standard Vertex AI
proxies that support the ``generateContent`` endpoint.

Coordinates are normalized to 0–999 by the model and denormalized to
pixel coordinates based on the actual screenshot dimensions.
"""

import json
import random
import time
import uuid
from io import BytesIO
from typing import Any

from loguru import logger
from PIL import Image

from mobile_world.agents.base import MCPAgent
from mobile_world.agents.utils.prompts.gemini_cua import GEMINI_CUA_SYSTEM_PROMPT
from mobile_world.runtime.utils.models import (
    ANSWER,
    APP_DICT,
    CLICK,
    DOUBLE_TAP,
    DRAG,
    FINISHED,
    INPUT_TEXT,
    KEYBOARD_ENTER,
    LONG_PRESS,
    MCP,
    NAVIGATE_BACK,
    NAVIGATE_HOME,
    OPEN_APP,
    UNKNOWN,
    WAIT,
    JSONAction,
)

COORD_SCALE = 1000
API_RETRY_TIMES = 30
API_RETRY_INTERVAL = 5

_KEY_MAP = {
    "back": NAVIGATE_BACK,
    "escape": NAVIGATE_BACK,
    "home": NAVIGATE_HOME,
    "enter": KEYBOARD_ENTER,
    "return": KEYBOARD_ENTER,
}

_ENV_MAP = {
    "mobile": "ENVIRONMENT_MOBILE",
    "browser": "ENVIRONMENT_BROWSER",
    "desktop": "ENVIRONMENT_DESKTOP",
}


def _custom_declarations() -> list[Any]:
    """FunctionDeclarations for ``answer`` and ``done`` actions."""
    from google.genai import types

    answer = types.FunctionDeclaration(
        name="answer",
        description=(
            "Provide the final answer to a question-type task. "
            "Use this when the task asks for specific information."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "text": types.Schema(
                    type=types.Type.STRING,
                    description="The answer to the question.",
                ),
            },
            required=["text"],
        ),
    )

    done = types.FunctionDeclaration(
        name="done",
        description=(
            "Signal that the task has been completed successfully. "
            "Use this for action-type tasks (e.g. 'open Settings', "
            "'send a message') once all required steps are finished."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "summary": types.Schema(
                    type=types.Type.STRING,
                    description="Brief summary of what was accomplished.",
                ),
            },
        ),
    )

    return [answer, done]


def _denorm(val: int, dim: int) -> int:
    """Normalized coordinate (0–999) → pixel coordinate."""
    return max(0, min(int(val / COORD_SCALE * dim), dim - 1))


class GeminiCUAAgent(MCPAgent):
    """Gemini Computer Use Agent for mobile automation.

    Uses ``client.models.generate_content()`` with the ``computerUse``
    tool and standard multi-turn ``contents`` history.  Works with any
    proxy that supports the ``generateContent`` endpoint.

    Constructor params
    ------------------
    model_name : str
        Gemini model id, e.g. ``"gemini-3.5-flash"``.
    llm_base_url : str | None
        Custom gateway / proxy URL.
    api_key : str
        API key passed via ``x-goog-api-key`` header.
    environment : str
        One of ``"mobile"`` (default), ``"browser"``, ``"desktop"``.
    system_instruction : str | None
        Optional system instruction.
    enable_prompt_injection_detection : bool
        Opt-in screenshot scanning for adversarial prompts (3.5 Flash).
    """

    def __init__(
        self,
        model_name: str = "gemini-3.5-flash",
        llm_base_url: str | None = None,
        api_key: str = "empty",
        runtime_conf: dict[str, Any] | None = None,
        system_instruction: str | None = None,
        enable_prompt_injection_detection: bool = True,
        environment: str = "mobile",
        thinking_level: str = "medium",
        media_resolution: str | None = "high",
        *args: Any,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self.model_name = model_name
        self.api_key = api_key
        self.llm_base_url = llm_base_url
        self.system_instruction = system_instruction or GEMINI_CUA_SYSTEM_PROMPT
        self.enable_prompt_injection_detection = enable_prompt_injection_detection
        self.environment = environment
        self.thinking_level = thinking_level
        self.media_resolution = media_resolution
        self.runtime_conf = dict(runtime_conf or {})

        self._build_genai_client()

        self._history: list[Any] = []
        self._pending_calls: list[dict[str, Any]] = []
        self._pending_fn_parts: list[Any] = []
        self._enter_after_type: bool = False
        self._step_count: int = 0
        self._last_raw_response: str = ""

    # ── client setup ─────────────────────────────────────────────────────

    def _build_genai_client(self) -> None:
        from google import genai

        self._session_id = str(uuid.uuid4())

        kw: dict[str, Any] = {}
        if self.llm_base_url:
            kw["api_key"] = self.api_key if self.api_key and self.api_key != "empty" else "empty"
            headers: dict[str, str] = {"session-id": self._session_id}
            kw["http_options"] = {
                "base_url": self.llm_base_url,
                "headers": headers,
            }
        elif self.api_key and self.api_key != "empty":
            kw["api_key"] = self.api_key

        self.genai_client = genai.Client(**kw)
        logger.debug(
            f"Built GenAI client (base_url={self.llm_base_url}, session_id={self._session_id})"
        )

    # ── lifecycle ────────────────────────────────────────────────────────

    def initialize_hook(self, instruction: str) -> None:
        self._build_genai_client()
        self.reset()

    def reset(self) -> None:
        self._history = []
        self._pending_calls = []
        self._pending_fn_parts = []
        self._enter_after_type = False
        self._step_count = 0
        self._last_raw_response = ""

    # ── tools & config ───────────────────────────────────────────────────

    def _build_config(self) -> Any:
        from google.genai import types

        env_str = _ENV_MAP.get(self.environment, self.environment)
        env_enum = types.Environment(env_str)
        cu = types.ComputerUse(
            environment=env_enum,
            enable_prompt_injection_detection=self.enable_prompt_injection_detection or None,
        )
        tools = [
            types.Tool(computer_use=cu),
            types.Tool(function_declarations=_custom_declarations()),
        ]

        cfg_kw: dict[str, Any] = {"tools": tools}
        if self.system_instruction:
            cfg_kw["system_instruction"] = self.system_instruction

        cfg_kw["thinking_config"] = types.ThinkingConfig(
            include_thoughts=True,
            thinking_level=self.thinking_level,  # type: ignore[arg-type]
        )

        if self.media_resolution:
            _MEDIA_RES_MAP: dict[str, Any] = {
                "ultra_high": "MEDIA_RESOLUTION_ULTRA_HIGH",
                "high": types.MediaResolution.MEDIA_RESOLUTION_HIGH,
                "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
                "low": types.MediaResolution.MEDIA_RESOLUTION_LOW,
            }
            if self.media_resolution in _MEDIA_RES_MAP:
                cfg_kw["media_resolution"] = _MEDIA_RES_MAP[self.media_resolution]

        return types.GenerateContentConfig(**cfg_kw)

    # ── API call ─────────────────────────────────────────────────────────

    _AREA_SCALE = 0.75  # resize to 3/4 of original area

    @staticmethod
    def _screenshot_bytes(screenshot: Image.Image) -> bytes:
        import math

        scale = math.sqrt(GeminiCUAAgent._AREA_SCALE)
        new_w = int(screenshot.width * scale)
        new_h = int(screenshot.height * scale)
        if (new_w, new_h) != screenshot.size:
            screenshot = screenshot.resize((new_w, new_h), Image.Resampling.LANCZOS)
        buf = BytesIO()
        screenshot.save(buf, format="PNG")
        return buf.getvalue()

    def _call_generate(self, screenshot: Image.Image, is_initial: bool) -> Any:
        from google.genai import types

        img_bytes = self._screenshot_bytes(screenshot)

        if is_initial:
            user_content = types.Content(
                role="user",
                parts=[
                    types.Part(text=self.instruction),
                    types.Part(inline_data=types.Blob(data=img_bytes, mime_type="image/png")),
                ],
            )
            contents = [user_content]
        else:
            fn_response_parts = list(self._pending_fn_parts)
            self._pending_fn_parts = []

            if fn_response_parts:
                last = fn_response_parts[-1]
                fr = last.function_response
                resp = dict(fr.response) if fr.response else {}
                resp["screenshot"] = {"$ref": "screenshot"}
                try:
                    fn_response_parts[-1] = types.Part(
                        function_response=types.FunctionResponse(
                            name=fr.name,
                            response=resp,
                            parts=[
                                types.FunctionResponsePart(
                                    inline_data=types.FunctionResponseBlob(
                                        mime_type="image/png",
                                        data=img_bytes,
                                        display_name="screenshot",
                                    )
                                )
                            ],
                        )
                    )
                except (AttributeError, TypeError):
                    fn_response_parts.append(
                        types.Part(
                            inline_data=types.Blob(
                                data=img_bytes,
                                mime_type="image/png",
                            )
                        ),
                    )
            else:
                fn_response_parts.append(
                    types.Part(
                        inline_data=types.Blob(
                            data=img_bytes,
                            mime_type="image/png",
                        )
                    ),
                )

            user_content = types.Content(role="user", parts=fn_response_parts)
            contents = self._history + [user_content]

        response = self.genai_client.models.generate_content(
            model=self.model_name,
            contents=contents,  # type: ignore[arg-type]
            config=self._build_config(),
        )

        self._history = list(contents)
        if response.candidates and response.candidates[0].content:
            self._history.append(response.candidates[0].content)

        return response

    # ── response parsing ─────────────────────────────────────────────────

    @staticmethod
    def _format_response(response: Any) -> str:
        parts_str: list[str] = []
        if not response.candidates:
            return "(no candidates)"
        for part in response.candidates[0].content.parts:
            if getattr(part, "thought", False) and part.text:
                parts_str.append(f"[Thought]: {part.text}")
            elif part.text:
                parts_str.append(f"[Model]: {part.text}")
            if part.function_call:
                args = dict(part.function_call.args) if part.function_call.args else {}
                intent = args.get("intent", "N/A")
                parts_str.append(
                    f"[Action]: {part.function_call.name}("
                    f"{json.dumps(args, ensure_ascii=False)}) "
                    f"| Intent: {intent}"
                )
        return "\n".join(parts_str) or "(empty response)"

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Extract non-thought user-visible text from the response."""
        if not response.candidates:
            return ""
        return " ".join(
            part.text
            for part in response.candidates[0].content.parts
            if part.text and not getattr(part, "thought", False)
        ).strip()

    @staticmethod
    def _extract_function_calls(response: Any) -> list[dict[str, Any]]:
        if not response.candidates:
            return []
        calls: list[dict[str, Any]] = []
        for part in response.candidates[0].content.parts:
            if part.function_call:
                calls.append(
                    {
                        "name": part.function_call.name,
                        "id": part.function_call.id or part.function_call.name,
                        "arguments": dict(part.function_call.args)
                        if part.function_call.args
                        else {},
                    }
                )
        return calls

    # ── action result helpers ────────────────────────────────────────────

    @staticmethod
    def _get_app_list() -> list[dict[str, str]]:
        """Return the curated MW app list from APP_DICT."""
        return [{"app_name": name, "package_name": pkg} for name, pkg in APP_DICT.items()]

    def _build_action_result(self, name: str) -> dict[str, Any]:
        """Return the function_response payload for a given action."""
        if name == "list_apps":
            return {"apps": self._get_app_list()}
        return {"status": "ok"}

    def _queue_fn_response(self, name: str, call_id: str, result: dict[str, Any]) -> None:
        """Queue a FunctionResponse part to send with the next user turn."""
        from google.genai import types

        self._pending_fn_parts.append(
            types.Part(
                function_response=types.FunctionResponse(
                    name=name,
                    response=result,
                )
            )
        )

    # ── action mapping ───────────────────────────────────────────────────

    def _convert_to_json_action(
        self,
        name: str,
        args: dict[str, Any],
        sw: int,
        sh: int,
    ) -> JSONAction | None:

        if name in ("click", "click_at"):
            return JSONAction(
                action_type=CLICK,
                x=_denorm(args["x"], sw),
                y=_denorm(args["y"], sh),
            )

        if name == "double_click":
            return JSONAction(
                action_type=DOUBLE_TAP,
                x=_denorm(args["x"], sw),
                y=_denorm(args["y"], sh),
            )

        if name == "long_press":
            return JSONAction(
                action_type=LONG_PRESS,
                x=_denorm(args["x"], sw),
                y=_denorm(args["y"], sh),
            )

        if name == "type":
            if args.get("press_enter", False):
                self._enter_after_type = True
            return JSONAction(action_type=INPUT_TEXT, text=str(args.get("text", "")))

        if name == "type_text_at":
            if args.get("press_enter", True):
                self._enter_after_type = True
            return JSONAction(
                action_type=INPUT_TEXT,
                text=str(args.get("text", "")),
                clear_text=args.get("clear_before_typing", True),
            )

        if name == "drag_and_drop":
            return JSONAction(
                action_type=DRAG,
                start_x=_denorm(args["start_x"], sw),
                start_y=_denorm(args["start_y"], sh),
                end_x=_denorm(args["end_x"], sw),
                end_y=_denorm(args["end_y"], sh),
            )

        if name == "go_back":
            return JSONAction(action_type=NAVIGATE_BACK)

        if name == "go_forward":
            return JSONAction(action_type=WAIT)

        if name == "open_app":
            return JSONAction(
                action_type=OPEN_APP,
                app_name=str(args.get("app_name", "") or args.get("package_name", "")),
            )

        if name == "answer":
            return JSONAction(
                action_type=ANSWER,
                text=str(args.get("text", "")),
            )

        if name == "done":
            return JSONAction(action_type=FINISHED)

        if name in ("wait", "wait_5_seconds"):
            return JSONAction(action_type=WAIT)

        if name in ("take_screenshot", "list_apps"):
            return None  # handled inline by predict — not a real device action

        if name == "press_key":
            key = str(args.get("key", "")).lower()
            if key in _KEY_MAP:
                return JSONAction(action_type=_KEY_MAP[key])
            return JSONAction(action_type=UNKNOWN, text=f"press_key: {key}")

        if name in ("key_combination", "hotkey"):
            keys = args.get("keys", args.get("key", ""))
            if isinstance(keys, list):
                keys = "+".join(keys)
            lower = keys.lower()
            for k, act in _KEY_MAP.items():
                if k in lower:
                    return JSONAction(action_type=act)
            return JSONAction(action_type=UNKNOWN, text=f"hotkey: {keys}")

        if name in (
            "hover_at",
            "move",
            "navigate",
            "search",
            "open_web_browser",
            "key_down",
            "key_up",
            "mouse_down",
            "mouse_up",
        ):
            return JSONAction(action_type=WAIT)

        if name in ("scroll", "scroll_document", "scroll_at"):
            return self._handle_scroll(args, sw, sh)

        if name in ("middle_click", "right_click", "triple_click"):
            return JSONAction(
                action_type=CLICK,
                x=_denorm(args["x"], sw),
                y=_denorm(args["y"], sh),
            )

        if self.tools:
            return JSONAction(action_type=MCP, action_name=name, action_json=args)

        return JSONAction(action_type=UNKNOWN, text=f"unhandled action: {name}")

    @staticmethod
    def _handle_scroll(
        args: dict[str, Any],
        sw: int,
        sh: int,
    ) -> JSONAction:
        direction = str(args.get("direction", "down"))
        cx = _denorm(args.get("x", 500), sw)
        cy = _denorm(args.get("y", 500), sh)
        if "magnitude_in_pixels" in args or "magnitude" in args:
            mag = int(args.get("magnitude_in_pixels", args.get("magnitude", 300)))
        elif "magnitude_in_wheel_clicks" in args:
            mag = int(args["magnitude_in_wheel_clicks"]) * 150
        else:
            mag = 300
        half_y = int(mag / COORD_SCALE * sh) // 2
        half_x = int(mag / COORD_SCALE * sw) // 2

        drag_map = {
            "down": (cx, cy + half_y, cx, cy - half_y),
            "up": (cx, cy - half_y, cx, cy + half_y),
            "left": (cx + half_x, cy, cx - half_x, cy),
            "right": (cx - half_x, cy, cx + half_x, cy),
        }
        if direction not in drag_map:
            return JSONAction(action_type=UNKNOWN, text=f"scroll: bad direction {direction}")
        sx, sy, ex, ey = drag_map[direction]
        return JSONAction(action_type=DRAG, start_x=sx, start_y=sy, end_x=ex, end_y=ey)

    # ── predict ──────────────────────────────────────────────────────────

    def _process_fn_call(
        self,
        fc: dict[str, Any],
        sw: int,
        sh: int,
    ) -> JSONAction | None:
        """Queue the function_response and return the JSONAction (None for virtual actions)."""
        result = self._build_action_result(fc["name"])
        self._queue_fn_response(fc["name"], fc["id"], result)
        return self._convert_to_json_action(fc["name"], fc["arguments"], sw, sh)

    def predict(self, observation: dict[str, Any]) -> tuple[str, JSONAction]:
        screenshot: Image.Image = observation["screenshot"]
        sw, sh = screenshot.size
        self._step_count += 1

        # 1) Synthetic enter after type(press_enter=True)
        if self._enter_after_type:
            self._enter_after_type = False
            logger.info("[GeminiCUA] Injecting KEYBOARD_ENTER after type")
            return self._last_raw_response, JSONAction(action_type=KEYBOARD_ENTER)

        # 2) Drain queued function_calls from a multi-action response
        while self._pending_calls:
            fc = self._pending_calls.pop(0)
            action = self._process_fn_call(fc, sw, sh)
            if action is not None:
                logger.info(
                    f"[GeminiCUA] Queued action: {fc['name']} "
                    f"| Intent: {fc['arguments'].get('intent', '')}"
                )
                return self._last_raw_response, action
            logger.info(f"[GeminiCUA] Virtual action (no-op): {fc['name']}")

        # 3) Call generateContent — loop until we get a real device action
        max_virtual_rounds = 5
        for _ in range(max_virtual_rounds):
            is_initial = len(self._history) == 0
            response = self._call_api(screenshot, is_initial)
            if response is None:
                return self._last_raw_response, JSONAction(
                    action_type=UNKNOWN, text="API call failed after retries"
                )

            raw = self._format_response(response)
            self._last_raw_response = raw
            logger.info(f"[GeminiCUA] Response:\n{raw}")

            fn_calls = self._extract_function_calls(response)

            if not fn_calls:
                text = self._extract_text(response)
                if text:
                    logger.info(
                        f"[GeminiCUA] Text without action (treating as answer): {text[:200]}"
                    )
                    return raw, JSONAction(action_type=ANSWER, text=text)
                # Only thought parts or empty — model is still reasoning, re-call
                logger.info("[GeminiCUA] No action or answer (thoughts only), re-calling")
                continue

            # Process calls until we find a real device action
            for i, fc in enumerate(fn_calls):
                action = self._process_fn_call(fc, sw, sh)
                if action is not None:
                    self._pending_calls = fn_calls[i + 1 :]
                    logger.info(
                        f"[GeminiCUA] Action: {fc['name']} "
                        f"| Intent: {fc['arguments'].get('intent', '')}"
                    )
                    return raw, action
                logger.info(f"[GeminiCUA] Virtual action (no-op): {fc['name']}")

            # All calls in this response were virtual — loop to get more

        return self._last_raw_response, JSONAction(
            action_type=UNKNOWN, text="exceeded virtual action rounds"
        )

    def _call_api(self, screenshot: Image.Image, is_initial: bool) -> Any:
        for attempt in range(API_RETRY_TIMES):
            try:
                logger.info(
                    f"[GeminiCUA] {'Initial' if is_initial else 'Continue'} "
                    f"call (step={self._step_count})"
                )
                response = self._call_generate(screenshot, is_initial)

                if response.prompt_feedback and response.prompt_feedback.block_reason:
                    logger.error(
                        f"[GeminiCUA] Blocked by safety: {response.prompt_feedback.block_reason}"
                    )
                    self._last_raw_response = f"blocked: {response.prompt_feedback.block_reason}"
                    return None

                if (
                    not response
                    or not response.candidates
                    or not response.candidates[0].content.parts
                ):
                    raise ValueError("No valid response from Gemini")

                return response
            except Exception as e:
                logger.error(
                    f"[GeminiCUA] API error (attempt {attempt + 1}/{API_RETRY_TIMES}): {e}"
                )
                if attempt >= API_RETRY_TIMES - 1:
                    self._last_raw_response = str(e)
                    return None
                time.sleep(API_RETRY_INTERVAL * min(2**attempt, 64) * random.uniform(1, 1.5))
        return None
