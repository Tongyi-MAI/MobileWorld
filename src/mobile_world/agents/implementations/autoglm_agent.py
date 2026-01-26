"""AutoGLM-Phone Agent implementation for MobileWorld.

This module provides an adapter for the AutoGLM-Phone VLM to work with
the MobileWorld evaluation framework by parsing AutoGLM's native output
format and converting it to MobileWorld's JSONAction format.
"""

import ast
import time
from datetime import datetime
from typing import Any

from loguru import logger

from mobile_world.agents.base import MCPAgent
from mobile_world.agents.utils.helpers import pil_to_base64
from mobile_world.runtime.utils.models import JSONAction


# AutoGLM System Prompt (Chinese version from Open-AutoGLM)
def get_autoglm_system_prompt() -> str:
    """Get the AutoGLM system prompt with current date."""
    today = datetime.today()
    formatted_date = today.strftime("%Y年%m月%d日")

    return (
        "今天的日期是: "
        + formatted_date
        + """
你是一个智能体分析专家，可以根据操作历史和当前状态图执行一系列操作来完成任务。
你必须严格按照要求输出以下格式：
<think>{think}</think>
<answer>{action}</answer>

其中：
- {think} 是对你为什么选择这个操作的简短推理说明。
- {action} 是本次执行的具体操作指令，必须严格遵循下方定义的指令格式。

操作指令及其作用如下：
- do(action="Launch", app="xxx")  
    Launch是启动目标app的操作，这比通过主屏幕导航更快。此操作完成后，您将自动收到结果状态的截图。
- do(action="Tap", element=[x,y])  
    Tap是点击操作，点击屏幕上的特定点。可用此操作点击按钮、选择项目、从主屏幕打开应用程序，或与任何可点击的用户界面元素进行交互。坐标系统从左上角 (0,0) 开始到右下角（999,999)结束。此操作完成后，您将自动收到结果状态的截图。
- do(action="Tap", element=[x,y], message="重要操作")  
    基本功能同Tap，点击涉及财产、支付、隐私等敏感按钮时触发。
- do(action="Type", text="xxx")  
    Type是输入操作，在当前聚焦的输入框中输入文本。使用此操作前，请确保输入框已被聚焦（先点击它）。输入的文本将像使用键盘输入一样输入。重要提示：手机可能正在使用 ADB 键盘，该键盘不会像普通键盘那样占用屏幕空间。要确认键盘已激活，请查看屏幕底部是否显示 'ADB Keyboard {ON}' 类似的文本，或者检查输入框是否处于激活/高亮状态。不要仅仅依赖视觉上的键盘显示。自动清除文本：当你使用输入操作时，输入框中现有的任何文本（包括占位符文本和实际输入）都会在输入新文本前自动清除。你无需在输入前手动清除文本——直接使用输入操作输入所需文本即可。操作完成后，你将自动收到结果状态的截图。
- do(action="Type_Name", text="xxx")  
    Type_Name是输入人名的操作，基本功能同Type。
- do(action="Interact")  
    Interact是当有多个满足条件的选项时而触发的交互操作，询问用户如何选择。
- do(action="Swipe", start=[x1,y1], end=[x2,y2])  
    Swipe是滑动操作，通过从起始坐标拖动到结束坐标来执行滑动手势。可用于滚动内容、在屏幕之间导航、下拉通知栏以及项目栏或进行基于手势的导航。坐标系统从左上角 (0,0) 开始到右下角（999,999)结束。滑动持续时间会自动调整以实现自然的移动。此操作完成后，您将自动收到结果状态的截图。
- do(action="Note", message="True")  
    记录当前页面内容以便后续总结。
- do(action="Call_API", instruction="xxx")  
    总结或评论当前页面或已记录的内容。
- do(action="Long Press", element=[x,y])  
    Long Pres是长按操作，在屏幕上的特定点长按指定时间。可用于触发上下文菜单、选择文本或激活长按交互。坐标系统从左上角 (0,0) 开始到右下角（999,999)结束。此操作完成后，您将自动收到结果状态的屏幕截图。
- do(action="Double Tap", element=[x,y])  
    Double Tap在屏幕上的特定点快速连续点按两次。使用此操作可以激活双击交互，如缩放、选择文本或打开项目。坐标系统从左上角 (0,0) 开始到右下角（999,999)结束。此操作完成后，您将自动收到结果状态的截图。
- do(action="Take_over", message="xxx")  
    Take_over是接管操作，表示在登录和验证阶段需要用户协助。
- do(action="Back")  
    导航返回到上一个屏幕或关闭当前对话框。相当于按下 Android 的返回按钮。使用此操作可以从更深的屏幕返回、关闭弹出窗口或退出当前上下文。此操作完成后，您将自动收到结果状态的截图。
- do(action="Home") 
    Home是回到系统桌面的操作，相当于按下 Android 主屏幕按钮。使用此操作可退出当前应用并返回启动器，或从已知状态启动新任务。此操作完成后，您将自动收到结果状态的截图。
- do(action="Wait", duration="x seconds")  
    等待页面加载，x为需要等待多少秒。
- finish(message="xxx")  
    finish是结束任务的操作，表示准确完整完成任务，message是终止信息。 

必须遵循的规则：
1. 在执行任何操作前，先检查当前app是否是目标app，如果不是，先执行 Launch。
2. 如果进入到了无关页面，先执行 Back。如果执行Back后页面没有变化，请点击页面左上角的返回键进行返回，或者右上角的X号关闭。
3. 如果页面未加载出内容，最多连续 Wait 三次，否则执行 Back重新进入。
4. 如果页面显示网络问题，需要重新加载，请点击重新加载。
5. 如果当前页面找不到目标联系人、商品、店铺等信息，可以尝试 Swipe 滑动查找。
6. 遇到价格区间、时间区间等筛选条件，如果没有完全符合的，可以放宽要求。
7. 在结束任务前请一定要仔细检查任务是否完整准确的完成，如果出现错选、漏选、多选的情况，请返回之前的步骤进行纠正。
"""
    )


def parse_autoglm_response(content: str) -> tuple[str, str]:
    """
    Parse the model response into thinking and action parts.

    Parsing rules (following Open-AutoGLM's client.py):
    1. If content contains 'finish(message=', everything before is thinking,
       everything from 'finish(message=' onwards is action.
    2. If rule 1 doesn't apply but content contains 'do(action=',
       everything before is thinking, everything from 'do(action=' onwards is action.
    3. Fallback: If content contains '<answer>', use legacy parsing with XML tags.
    4. Otherwise, return empty thinking and full content as action.

    Args:
        content: Raw response content from LLM.

    Returns:
        Tuple of (thinking, action_str).
    """
    # Rule 1: Check for finish(message=
    if "finish(message=" in content:
        parts = content.split("finish(message=", 1)
        thinking = parts[0].strip()
        action_str = "finish(message=" + parts[1]
        return thinking, action_str

    # Rule 2: Check for do(action=
    if "do(action=" in content:
        parts = content.split("do(action=", 1)
        thinking = parts[0].strip()
        action_str = "do(action=" + parts[1]
        return thinking, action_str

    # Rule 3: Fallback to legacy XML tag parsing
    if "<answer>" in content:
        parts = content.split("<answer>", 1)
        thinking = parts[0].replace("<think>", "").replace("</think>", "").strip()
        action_str = parts[1].replace("</answer>", "").strip()
        return thinking, action_str

    # Rule 4: No markers found, return content as action
    return "", content


def parse_autoglm_action(action_str: str) -> dict[str, Any]:
    """
    Parse action string from AutoGLM response into a dictionary.

    Supports formats:
    - do(action="Tap", element=[x,y])
    - do(action="Type", text="xxx")
    - finish(message="xxx")
    etc.

    Args:
        action_str: Raw action string from model.

    Returns:
        Parsed action dictionary with '_metadata' field.

    Raises:
        ValueError: If the action cannot be parsed.
    """
    try:
        action_str = action_str.strip()
        
        # Clean up: extract only the first line if multiple lines present
        # This handles cases where LLM outputs extra text after the action
        lines = action_str.split('\n')
        if len(lines) > 1:
            # Find the line that starts with 'do(' or 'finish('
            for line in lines:
                line = line.strip()
                if line.startswith('do(') or line.startswith('finish('):
                    action_str = line
                    break
            else:
                # If no line starts with do/finish, use the first non-empty line
                action_str = lines[0].strip()
        
        logger.debug(f"Parsing action string: {repr(action_str)}")

        # Handle Type action specially (may contain special characters in text)
        if action_str.startswith('do(action="Type"') or action_str.startswith(
            'do(action="Type_Name"'
        ):
            # Extract text value
            text_start = action_str.find("text=")
            if text_start != -1:
                # Find the opening quote
                quote_start = action_str.find('"', text_start + 5)
                if quote_start != -1:
                    # Find matching closing quote (handle escaped quotes)
                    quote_end = len(action_str) - 1
                    while quote_end > quote_start and action_str[quote_end] != '"':
                        quote_end -= 1
                    # Remove trailing ')' if present
                    while quote_end > quote_start and action_str[quote_end] in ')':
                        quote_end -= 1
                    if action_str[quote_end] == '"':
                        text = action_str[quote_start + 1 : quote_end]
                        action_type = "Type_Name" if "Type_Name" in action_str else "Type"
                        return {"_metadata": "do", "action": action_type, "text": text}

            raise ValueError(f"Failed to parse Type action: {action_str}")

        elif action_str.startswith("do"):
            # Use AST parsing for safety
            try:
                # First, ensure the string is a single line for AST parsing
                # Remove any actual newlines that might be in the string
                cleaned = action_str.strip()
                
                # Only escape if there are literal backslashes that need escaping
                # Don't escape newlines as we've already removed them
                tree = ast.parse(cleaned, mode="eval")
                if not isinstance(tree.body, ast.Call):
                    raise ValueError("Expected a function call")

                call = tree.body
                # Extract keyword arguments safely
                action = {"_metadata": "do"}
                for keyword in call.keywords:
                    key = keyword.arg
                    value = ast.literal_eval(keyword.value)
                    action[key] = value

                return action
            except (SyntaxError, ValueError) as e:
                logger.error(f"AST parsing failed for: {repr(cleaned)}")
                raise ValueError(f"Failed to parse do() action: {e}")

        elif action_str.startswith("finish"):
            # Extract message from finish(message="xxx")
            message_start = action_str.find('message="')
            if message_start != -1:
                message_start += 9  # len('message="')
                message_end = action_str.rfind('"')
                if message_end > message_start:
                    message = action_str[message_start:message_end]
                    return {"_metadata": "finish", "message": message}

            # Fallback: try to extract any text after 'finish(message='
            if "finish(message=" in action_str:
                message = action_str.replace("finish(message=", "")[1:-2]
                return {"_metadata": "finish", "message": message}

            return {"_metadata": "finish", "message": "Task completed"}

        else:
            raise ValueError(f"Unknown action format: {action_str}")

    except Exception as e:
        raise ValueError(f"Failed to parse action: {e}")


def convert_autoglm_to_jsonaction(
    action_dict: dict[str, Any],
    screen_width: int,
    screen_height: int,
    scale_factor: int = 1000,
) -> JSONAction:
    """
    Convert AutoGLM action dictionary to MobileWorld JSONAction.

    Args:
        action_dict: Parsed AutoGLM action dictionary.
        screen_width: Width of the screenshot image.
        screen_height: Height of the screenshot image.
        scale_factor: Scale factor for coordinate normalization (default 1000).

    Returns:
        JSONAction object for MobileWorld runtime.
    """
    metadata = action_dict.get("_metadata")

    # Handle finish action
    if metadata == "finish":
        message = action_dict.get("message", "Task completed")
        return JSONAction(action_type="answer", text=message)

    # Handle do actions
    if metadata != "do":
        logger.warning(f"Unknown metadata type: {metadata}")
        return JSONAction(action_type="unknown", text=f"Unknown action: {action_dict}")

    action_name = action_dict.get("action", "")

    # Tap -> click
    if action_name == "Tap":
        element = action_dict.get("element", [0, 0])
        x = int(element[0] * screen_width / scale_factor)
        y = int(element[1] * screen_height / scale_factor)
        return JSONAction(action_type="click", x=x, y=y)

    # Type / Type_Name -> input_text
    elif action_name in ("Type", "Type_Name"):
        text = action_dict.get("text", "")
        return JSONAction(action_type="input_text", text=text)

    # Swipe -> drag
    elif action_name == "Swipe":
        start = action_dict.get("start", [0, 0])
        end = action_dict.get("end", [0, 0])
        start_x = int(start[0] * screen_width / scale_factor)
        start_y = int(start[1] * screen_height / scale_factor)
        end_x = int(end[0] * screen_width / scale_factor)
        end_y = int(end[1] * screen_height / scale_factor)
        return JSONAction(
            action_type="drag",
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
        )

    # Long Press -> long_press
    elif action_name == "Long Press":
        element = action_dict.get("element", [0, 0])
        x = int(element[0] * screen_width / scale_factor)
        y = int(element[1] * screen_height / scale_factor)
        return JSONAction(action_type="long_press", x=x, y=y)

    # Double Tap -> double_tap
    elif action_name == "Double Tap":
        element = action_dict.get("element", [0, 0])
        x = int(element[0] * screen_width / scale_factor)
        y = int(element[1] * screen_height / scale_factor)
        return JSONAction(action_type="double_tap", x=x, y=y)

    # Back -> navigate_back
    elif action_name == "Back":
        return JSONAction(action_type="navigate_back")

    # Home -> navigate_home
    elif action_name == "Home":
        return JSONAction(action_type="navigate_home")

    # Launch -> open_app
    elif action_name == "Launch":
        app_name = action_dict.get("app", "")
        return JSONAction(action_type="open_app", app_name=app_name)

    # Wait -> wait
    elif action_name == "Wait":
        return JSONAction(action_type="wait")

    # Interact -> ask_user (partial compatibility)
    elif action_name == "Interact":
        return JSONAction(
            action_type="ask_user", text="有多个选项满足条件，请指定您的选择"
        )

    # Take_over -> ask_user (partial compatibility)
    elif action_name == "Take_over":
        message = action_dict.get("message", "需要用户协助")
        return JSONAction(action_type="ask_user", text=message)

    # Note -> wait (unsupported, log warning)
    elif action_name == "Note":
        logger.warning("AutoGLM 'Note' action is not supported, treating as wait")
        return JSONAction(action_type="wait")

    # Call_API -> wait (unsupported, log warning)
    elif action_name == "Call_API":
        logger.warning("AutoGLM 'Call_API' action is not supported, treating as wait")
        instruction = action_dict.get("instruction", "")
        # Could potentially return as answer if needed
        return JSONAction(action_type="wait")

    else:
        logger.warning(f"Unknown AutoGLM action: {action_name}")
        return JSONAction(action_type="unknown", text=f"Unknown action: {action_name}")


class AutoGLMAgentMCP(MCPAgent):
    """
    AutoGLM-Phone Agent adapter for MobileWorld evaluation framework.

    This agent uses the AutoGLM-Phone VLM and adapts its output format
    to work with MobileWorld's JSONAction-based runtime.
    """

    def __init__(
        self,
        model_name: str,
        llm_base_url: str,
        api_key: str = "empty",
        observation_type: str = "screenshot",
        runtime_conf: dict = {
            "history_n_images": 3,
            "temperature": 0.0,
            "max_tokens": 3000,
        },
        tools: list[dict] = [],
        scale_factor: int = 1000,
        **kwargs,
    ):
        super().__init__(tools=tools, **kwargs)

        # Agent parameters
        self.model_name = model_name
        self.llm_base_url = llm_base_url
        self.api_key = api_key
        self.observation_type = observation_type
        self.runtime_conf = runtime_conf
        self.scale_factor = scale_factor

        logger.debug(f"AutoGLM Agent runtime_conf = {self.runtime_conf}")
        logger.debug(f"AutoGLM Agent scale_factor = {self.scale_factor}")

        self.build_openai_client(self.llm_base_url, self.api_key)
        logger.debug(f"AutoGLM Agent base_url={self.llm_base_url} model={self.model_name}")

        self.history_n_images = self.runtime_conf.pop("history_n_images", 3)
        self.history_images = []
        self.history_responses = []
        self.actions = []

    def initialize_hook(self, instruction: str) -> None:
        """Hook for initializing the agent with instruction."""
        logger.info(f"Initializing AutoGLM agent with instruction: {instruction}")
        self.reset()

    def _get_user_message(
        self, img_data, tool_call_res, ask_user_response_res, is_first: bool = False
    ) -> dict:
        """Build user message for conversation."""
        if tool_call_res is not None:
            return {
                "role": "user",
                "content": [{"type": "text", "text": f"Tool call result: {tool_call_res}"}],
            }
        elif ask_user_response_res is not None:
            return {
                "role": "user",
                "content": [{"type": "text", "text": ask_user_response_res}],
            }
        else:
            # Build screen info (similar to AutoGLM's MessageBuilder)
            text_content = ""
            if is_first:
                text_content = f"用户任务: {self.instruction}\n\n当前屏幕截图如下:"
            else:
                text_content = "** Screen Info **\n\n当前屏幕截图如下:"

            return {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": img_data,
                    },
                    {"type": "text", "text": text_content},
                ],
            }

    def _hide_history_images(self, messages: list[dict]) -> list[dict]:
        """Keep only recent N images in history to save context."""
        num_images_used = 0
        for i in range(len(messages)):
            reverse_i = len(messages) - i - 1
            msg = messages[reverse_i]
            if msg["role"] == "user" and isinstance(msg["content"], list):
                has_image = any(
                    item.get("type") == "image_url" for item in msg["content"]
                )
                if has_image:
                    if num_images_used < self.history_n_images:
                        # Encode image to base64
                        for item in msg["content"]:
                            if item.get("type") == "image_url":
                                img = item["image_url"]
                                if not isinstance(img, dict):
                                    encoded = pil_to_base64(img)
                                    item["image_url"] = {
                                        "url": f"data:image/png;base64,{encoded}"
                                    }
                        num_images_used += 1
                    else:
                        # Remove image, keep text only
                        messages[reverse_i]["content"] = [
                            item
                            for item in msg["content"]
                            if item.get("type") != "image_url"
                        ] or [{"type": "text", "text": "(Previous turn, screen not shown)"}]
        return messages

    def predict(
        self,
        observation: dict[str, Any],
    ) -> tuple[str, JSONAction]:
        """
        Generate action based on the current observation.

        Args:
            observation: Observation containing screenshot.

        Returns:
            Tuple of (raw_response, JSONAction).
        """
        obs_image = observation["screenshot"]
        orig_width, orig_height = obs_image.size
        tool_call = observation.get("tool_call", None)
        ask_user_response = observation.get("ask_user_response", None)

        is_first = len(self.history_images) == 0
        self.history_images.append((obs_image, tool_call, ask_user_response))

        logger.debug(f"Current history images count: {len(self.history_images)}")
        logger.debug(f"Current history responses count: {len(self.history_responses)}")

        assert len(self.history_images) == len(self.history_responses) + 1

        # Build messages with AutoGLM system prompt
        messages = [
            {
                "role": "system",
                "content": get_autoglm_system_prompt(),
            },
            self._get_user_message(
                self.history_images[0][0],
                self.history_images[0][1],
                self.history_images[0][2],
                is_first=True,
            ),
        ]

        # Add history
        for i, history_resp in enumerate(self.history_responses):
            history_img_data, tool_call_res, ask_user_response_res = self.history_images[
                i + 1
            ]

            # Assistant response (in AutoGLM format)
            response_message = {
                "role": "assistant",
                "content": history_resp.get("content", ""),
            }
            messages.append(response_message)

            # User message with next screenshot
            user_message = self._get_user_message(
                history_img_data, tool_call_res, ask_user_response_res, is_first=False
            )
            messages.append(user_message)

        logger.debug(f"Constructed {len(messages) // 2} history turns.")
        messages = self._hide_history_images(messages)

        # Try to get response
        try_times = 3
        response = None
        thinking = None
        action_str = None

        while try_times > 0:
            try:
                response = self.openai_chat_completions_create(
                    model=self.model_name,
                    messages=messages,
                    retry_times=1,
                    **self.runtime_conf,
                )

                # Parse AutoGLM format response
                thinking, action_str = parse_autoglm_response(response)

                logger.info(f"\nRaw LLM response received:\n{response}")
                logger.info(f"Parsed thinking: {thinking[:200]}..." if len(thinking) > 200 else f"Parsed thinking: {thinking}")
                logger.info(f"Parsed action_str: {repr(action_str)}")
                break

            except Exception as e:
                logger.warning(
                    f"Error fetching response from agent: {self.model_name}, {self.llm_base_url}"
                )
                error_msg = str(e)
                try_times -= 1
                logger.warning(
                    f"Error: {error_msg}. Retrying... ({try_times} attempts left)"
                )
                if "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                    time.sleep(2)

        if response is None:
            raise ValueError("AutoGLM Agent LLM failed")

        if action_str is None:
            return "Agent LLM failed", JSONAction(
                action_type="unknown", text="Agent LLM failed"
            )

        # Parse and convert action
        try:
            action_dict = parse_autoglm_action(action_str)
            json_action = convert_autoglm_to_jsonaction(
                action_dict, orig_width, orig_height, self.scale_factor
            )
        except Exception as e:
            logger.error(f"Error parsing AutoGLM action: {e}")
            logger.debug(f"Action string was: {action_str}")
            return response, JSONAction(action_type="unknown", text=f"Parse error: {e}")

        logger.info(f"Converted to JSONAction: {json_action}")

        # Update history
        self.history_responses.append({"role": "assistant", "content": response})
        self.actions.append(json_action.model_dump())
        logger.debug("Agent state updated for next turn.")

        return response, json_action

    def reset(self):
        """Reset the agent for the next task."""
        self.history_images = []
        self.history_responses = []
        self.actions = []
        logger.debug("AutoGLM Agent reset completed")
