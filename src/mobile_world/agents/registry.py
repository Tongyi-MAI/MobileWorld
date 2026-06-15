"""
Agent registry and configuration management.
"""

import importlib.util
import inspect
import os
import sys
from pathlib import Path

from loguru import logger

from mobile_world.agents.base import BaseAgent
from mobile_world.agents.implementations.gelab_agent import GelabAgent
from mobile_world.agents.implementations.general_e2e_agent import GeneralE2EAgentMCP
from mobile_world.agents.implementations.mai_ui_agent import MAIUINaivigationAgent
from mobile_world.agents.implementations.memgui_agent import MemGUIAgent
from mobile_world.agents.implementations.planner_executor import PlannerExecutorAgentMCP
from mobile_world.agents.implementations.qwen3vl import Qwen3VLAgentMCP
from mobile_world.agents.implementations.seed_agent import SeedAgent
from mobile_world.agents.implementations.ui_venus_agent import VenusNaviAgent
from mobile_world.agents.implementations.gui_owl_1_5 import GUIOWL15AgentMCP

AGENT_CONFIGS = {
    "qwen3vl": {
        "class": Qwen3VLAgentMCP,
    },
    "planner_executor": {
        "class": PlannerExecutorAgentMCP,
    },
    "mai_ui_agent": {
        "class": MAIUINaivigationAgent,
    },
    "general_e2e": {
        "class": GeneralE2EAgentMCP,
    },
    "seed_agent": {
        "class": SeedAgent,
    },
    "gelab_agent": {
        "class": GelabAgent,
    },
    "ui_venus_agent": {
        "class": VenusNaviAgent,
    },
    "gui_owl_1_5": {
        "class": GUIOWL15AgentMCP,
    },
    "memgui": {
        "class": MemGUIAgent,
    },
}


def load_agent_from_file(file_path: str) -> type[BaseAgent]:
    """Load an agent class from a Python file.

    Args:
        file_path: Path to the Python file containing the agent class

    Returns:
        The agent class that inherits from BaseAgent

    Raises:
        ValueError: If no agent class is found or multiple are found
        FileNotFoundError: If the file doesn't exist
    """
    file_path = os.path.abspath(file_path)

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Agent file not found: {file_path}")

    if not file_path.endswith(".py"):
        raise ValueError(f"Agent file must be a Python file (.py): {file_path}")

    # Load the module from file
    module_name = Path(file_path).stem
    spec = importlib.util.spec_from_file_location(module_name, file_path)

    if spec is None or spec.loader is None:
        raise ValueError(f"Could not load module from {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Find all classes that inherit from BaseAgent
    agent_classes = []
    for name, obj in inspect.getmembers(module, inspect.isclass):
        # Check if it's a subclass of BaseAgent but not BaseAgent itself
        if issubclass(obj, BaseAgent) and obj is not BaseAgent:
            agent_classes.append((name, obj))

    if len(agent_classes) == 0:
        raise ValueError(f"No class inheriting from BaseAgent found in {file_path}")

    if len(agent_classes) > 1:
        class_names = [name for name, _ in agent_classes]
        logger.warning(
            f"Multiple agent classes found in {file_path}: {class_names}. Using the first one: {class_names[0]}"
        )

    agent_name, agent_class = agent_classes[0]
    logger.info(f"Loaded agent class '{agent_name}' from {file_path}")

    return agent_class


def create_agent(
    agent_type: str, model_name: str, llm_base_url: str, api_key: str = "empty", **kwargs
):
    """Create an agent instance based on the agent type.

    Args:
        agent_type: Either a registered agent type name or path to a Python file containing an agent class
        model_name: Name of the model to use
        llm_base_url: Base URL for the LLM service
        api_key: API key for the LLM service
        **kwargs: Additional keyword arguments to pass to the agent

    Returns:
        An instance of the agent
    """
    if agent_type.endswith(".py") or os.path.exists(agent_type):
        agent_class = load_agent_from_file(agent_type)
        try:
            return agent_class(
                model_name=model_name,
                llm_base_url=llm_base_url,
                api_key=api_key,
                **kwargs,
            )
        except Exception as e:
            raise ValueError(f"Error creating agent: {e}")

    # Otherwise, use the registry
    if agent_type not in AGENT_CONFIGS:
        raise ValueError(f"Unsupported agent type: {agent_type}")

    return AGENT_CONFIGS[agent_type]["class"](
        model_name=model_name,
        llm_base_url=llm_base_url,
        tools=kwargs["env"].tools,
        api_key=api_key,
        **kwargs,
    )
