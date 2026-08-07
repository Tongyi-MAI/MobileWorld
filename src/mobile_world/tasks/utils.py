from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()

if TYPE_CHECKING:
    from mobile_world.runtime.controller import AndroidController


def wait_for_execution(controller: "AndroidController" = None, answer_text: str = None):
    """
    Wait for user to manually execute the action to finsih the task, only for testing.
    """
    print("\n" + "=" * 70)
    print("  Please manually exeuction action on GUI...")
    print("  Press Enter when done or input the answer text")
    print("=" * 70)
    answer = input()
    if answer == "":
        return
    else:
        if controller is not None:
            controller.interaction_cache = answer


@dataclass
class ModelConfig:
    model_name: str
    api_key: str
    url: str


def user_agent_answer_question(
    sys_prompt: str,
    agent_question: str,
    model_config: ModelConfig,
    chat_history: list[dict[str, str]] = None,
) -> str:
    """
    Use LLM to mock the user to answer the agent question.
    stateless implementation, no need to save the conversation history.
    """
    # The MW server runs clock-shifted (libtimeshift) so date-relative verifiers see the
    # task timeframe; that shifted clock makes the LLM endpoint's TLS cert read "not yet
    # valid" -> skip cert verification for this mock-user call (trusted endpoint, still TLS).
    llm = OpenAI(
        base_url=model_config.url,
        api_key=model_config.api_key,
        http_client=httpx.Client(verify=False),
    )
    if chat_history is None:
        chat_history = []

    messages = (
        [{"role": "system", "content": sys_prompt}]
        + chat_history
        + [{"role": "user", "content": agent_question}]
    )
    response = llm.chat.completions.create(
        model=model_config.model_name,
        messages=messages,
        temperature=0.0,
        # max_tokens=1024,
        top_p=1.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        # extra_body={"repetition_penalty": 1.0, "top_k": -1},
        seed=42,
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    import os

    sys_prompt = "You are a helpful assistant."
    agent_question = "What is the capital of France?"
    from mobile_world.runtime.utils.helpers import mask_api_key

    print(os.getenv("USER_AGENT_MODEL"))
    print(mask_api_key(os.getenv("USER_AGENT_API_KEY")))
    print(os.getenv("USER_AGENT_BASE_URL"))
    model_config = ModelConfig(
        model_name=os.getenv("USER_AGENT_MODEL"),
        api_key=os.getenv("USER_AGENT_API_KEY"),
        url=os.getenv("USER_AGENT_BASE_URL"),
    )
    answer = user_agent_answer_question(sys_prompt, agent_question, model_config)
    print(answer)
