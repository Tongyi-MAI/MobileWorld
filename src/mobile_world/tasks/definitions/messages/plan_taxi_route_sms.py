"""Plan shortest taxi route in Chengdu and send SMS with route details."""

import re

from mobile_world.runtime.app_helpers.system import get_sent_sms_bodies_via_adb
from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


class PlanTaxiRouteSmsTask(BaseTask):
    """Plan a shortest taxi route in Chengdu that visits landmarks and send SMS."""

    goal = (
        "Please help me plan exactly 1 shortest taxi route in Chengdu that:\n"
        'Starts at "成都双流国际机场T2航站楼" and ends at my hotel "成都市锦江区春熙路南段8号".\n'
        "On the way, I must visit exactly these 2 landmarks (in any order):\n"
        '1. "宽窄巷子"\n'
        '2. "锦里古街"\n'
        "请短信发送下面的内容给我的旅行伙伴Lucy 13900139000：\n"
        "4个地点名称和坐标：[名称：坐标，经度,纬度，逗号分隔]\n "
        "最短距离的地点浏览顺序，逗号分隔\n "
        "三段打车的驾车距离（米），按顺序计算，逗号分隔\n "
        "总驾车距离（米）\n "
    )
    task_tags = {"agent-mcp", "lang-en"}

    RECIPIENT_PHONE = "13900139000"

    # Location coordinates for validation
    LOCATIONS = {
        "成都双流国际机场T2航站楼": "103.954825,30.570338",
        "宽窄巷子": "82.070408,44.886769",  # User provided coordinate
        "锦里古街": "104.049828,30.645994",
        "成都市锦江区春熙路南段8号": "104.076842,30.654076",
    }

    EXPECTED_DISTANCES = {
        ("成都双流国际机场T2航站楼", "锦里古街"): 19126,
        ("锦里古街", "宽窄巷子"): 3243285,
        (
            "宽窄巷子",
            "成都市锦江区春熙路南段8号",
        ): 3229707,
    }

    # Expected route order (shortest path)
    EXPECTED_ROUTE_ORDER = [
        "成都双流国际机场T2航站楼",
        "锦里古街",
        "宽窄巷子",
        "成都市锦江区春熙路南段8号",
    ]

    # Expected segment distances (in meters)
    EXPECTED_SEGMENT_DISTANCES = [19126, 3243285, 3229707]
    EXPECTED_TOTAL_DISTANCE = 6492118  # Sum of segments

    app_names = {"MCP-Amap", "Messages"}

    async def is_successful_async(self, controller: AndroidController) -> float | tuple[float, str]:
        """Check if the task is successful."""
        self._check_is_initialized()

        # Check 1: Verify SMS was sent
        sms_bodies = get_sent_sms_bodies_via_adb(controller, self.RECIPIENT_PHONE)
        if not sms_bodies:
            return 0.0, f"SMS not found sent to {self.RECIPIENT_PHONE}"

        lines = [line.strip() for line in sms_bodies[0].splitlines() if line.strip()]

        if len(lines) < 4:
            return 0.0, f"Expected at least 4 lines in SMS, found {len(lines)}"

        # Check 2: Verify first line contains all 4 locations with exact coordinates
        first_line = lines[0]
        for location, coord in self.LOCATIONS.items():
            if location not in first_line:
                return 0.0, f"Location '{location}' not found in first line"
            # Verify exact coordinate match
            if coord not in first_line:
                return 0.0, f"Coordinate '{coord}' for '{location}' not found in first line"

        # Check 3: Verify second line contains route order (at least 4 locations)
        route_line = lines[1]
        route_text = route_line.split("：")[-1].split(":")[-1].strip()
        route_parts = [part.strip() for part in re.split(r"[，,]+", route_text) if part.strip()]

        if len(route_parts) < 4:
            return 0.0, f"Route must have at least 4 locations, found {len(route_parts)}"

        # Check 4: Verify third line contains distances (at least 3 numbers)
        distance_line = lines[2]
        distance_str = distance_line.split("：")[-1].split(":")[-1].strip()
        distances = [
            int(re.sub(r"[^\d]", "", d))
            for d in re.split(r"[，,]+", distance_str)
            if re.sub(r"[^\d]", "", d)
        ]

        if len(distances) < 3:
            return 0.0, f"Expected at least 3 segment distances, found {len(distances)}"

        # Check 5: Verify fourth line contains total distance
        total_line = lines[3]
        total_distance_match = re.search(r"[\d,]+", total_line)
        if not total_distance_match:
            return 0.0, "Total distance number not found"

        return 1.0

    def tear_down(self, controller: AndroidController) -> bool:
        super().tear_down(controller)
        return True
