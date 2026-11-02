from loguru import logger

from mobile_world.tasks.registry import TaskRegistry


def test_every_task_has_exactly_one_language_tag():
    logger.disable("mobile_world")
    try:
        registry = TaskRegistry()
        offenders = {}
        for name in registry.list_tasks():
            tags = set(getattr(registry.get_task(name), "task_tags", None) or ())
            lang_tags = sorted(tag for tag in tags if tag.startswith("lang-"))
            if len(lang_tags) != 1:
                offenders[name] = lang_tags
    finally:
        logger.enable("mobile_world")

    assert offenders == {}
