"""Adjust font and icon size task implementation."""

from loguru import logger

from mobile_world.runtime.app_helpers.system import (
    get_display_density,
    get_display_size_density_bounds,
    get_font_scale,
)
from mobile_world.runtime.controller import AndroidController
from mobile_world.runtime.utils.device import is_redroid
from mobile_world.tasks.base import BaseTask


class AdjustFontIconMaximumTask(BaseTask):
    """Adjust font and icon size to maximum task."""

    goal = "Increase the font size and icons on your phone to the maximum setting."

    target_font_scale = 2.0
    # Legacy QEMU-emulator value. Preserved for non-redroid and redroid probe fallback.
    target_density = 540
    density_tolerance = 2

    task_tags = {"lang-en"}

    def __init__(self):
        super().__init__()

    app_names = {
        "Settings",
    }

    def initialize_task_hook(self, controller: AndroidController) -> bool:
        """Initialize task - save current font scale and display density."""
        self._original_font_scale = get_font_scale(controller)
        self._original_density = get_display_density(controller)
        return True

    def is_successful(self, controller: AndroidController) -> float | tuple[float, str]:
        """Check if task is successful - font and icon sizes should be at maximum."""
        self._check_is_initialized()

        current_font_scale = get_font_scale(controller)
        current_density = get_display_density(controller)

        logger.info(
            f"Current settings - Font scale: {current_font_scale}, Display density: {current_density}"
        )
        logger.info(
            f"Original settings - Font scale: {self._original_font_scale}, Display density: {self._original_density}"
        )

        font_at_max = current_font_scale == self.target_font_scale
        expected_density = self.target_density
        icons_at_max = current_density == self.target_density
        if is_redroid(controller.device):
            _, max_density = get_display_size_density_bounds(controller)
        else:
            max_density = 0
        if max_density > 0:
            icons_at_max = abs(current_density - max_density) <= self.density_tolerance
            expected_density = max_density

        if font_at_max and icons_at_max:
            return 1.0, "Success"
        else:
            return (
                0.0,
                f"Font and display size are not at maximum settings, current font scale: {current_font_scale}, current density: {current_density}, expected density: {expected_density}",
            )
