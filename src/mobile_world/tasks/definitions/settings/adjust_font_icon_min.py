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


class AdjustFontIconMinimumTask(BaseTask):
    """Adjust font and icon size to minimum task."""

    goal = "Decrease the font size and icons on your phone to the minimum setting."

    target_font_scale = 0.85
    # Legacy QEMU-emulator value. Preserved for non-redroid and redroid probe fallback.
    target_density = 356
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
        """Check if task is successful - font and icon sizes should be at minimum."""
        self._check_is_initialized()

        current_font_scale = get_font_scale(controller)
        current_density = get_display_density(controller)

        logger.info(
            f"Current settings - Font scale: {current_font_scale}, Display density: {current_density}"
        )
        logger.info(
            f"Original settings - Font scale: {self._original_font_scale}, Display density: {self._original_density}"
        )

        font_at_min = current_font_scale == self.target_font_scale
        expected_density = self.target_density
        icons_at_min = current_density == self.target_density
        if is_redroid(controller.device):
            min_density, _ = get_display_size_density_bounds(controller)
        else:
            min_density = 0
        if min_density > 0:
            # AOSP derives this bound with float-to-int rounding. The legacy x86
            # verifier remains exact below; redroid's 280-DPI display reports 238.
            icons_at_min = abs(current_density - min_density) <= self.density_tolerance
            expected_density = min_density

        if font_at_min and icons_at_min:
            return 1.0, "Success"
        else:
            return (
                0.0,
                f"Font and display size are not at minimum settings, current font scale: {current_font_scale}, current density: {current_density}, expected density: {expected_density}",
            )
