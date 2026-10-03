"""Plan multimodal commute route in Shanghai and send SMS with route details."""

import re

from mobile_world.runtime.app_helpers.system import get_sent_sms_bodies_via_adb
from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


class PlanCommuteRouteSmsTask(BaseTask):
    """Plan a multimodal commute route in Shanghai and send SMS with route details."""

    goal = (
        "Please help me design exactly 1 multimodal commute route in Shanghai that:\n"
        'Starts at my home: "上海市徐汇区漕溪北路41号" and ends at my office: "上海市浦东新区世纪大道100号".\n'
        "The route must contain exactly 3 segments in this fixed order:\n"
        "1) walking from home to a nearby metro or bus station;\n"
        "2) integrated public transit (metro / bus) between two stations;\n"
        "3) walking from the arrival station to my office.\n"
        "帮我找出总通勤时间小于50min，且步行时间最短的路线；"
        "请短信发送下面的内容给我的同事Tom 13800138000：\n"
        "起点、终点、需乘地铁的起止站和对应的坐标：[名称：坐标，逗号分隔]\n "
        "步行路段的instruction，逗号分隔\n "
        "步行和乘坐地铁的总距离（米），逗号分隔\n "
    )
    task_tags = {"agent-mcp", "lang-en"}

    RECIPIENT_PHONE = "13800138000"

    LOCATIONS = {
        "上海市徐汇区漕溪北路41号": "121.439307,31.192140",
        "上海市浦东新区世纪大道100号": "121.507572,31.234583",
        "徐家汇": "121.433428,31.193030",
        "人民广场": "121.476629,31.232076",
        "世纪大道浦东南路": "121.516488,31.209918",
    }

    EXPECTED_WALKING_DISTANCE = 780
    EXPECTED_TRANSIT_DISTANCE = 10340

    EXPECTED_WALKING_INSTRUCTIONS = [
        "步行24米向右前方行走",
        "步行21米左转",
        "步行15米",
        "步行64米到达徐家汇",
        "步行245米左转",
        "步行30米右转",
        "沿西藏中路步行21米到达人民广场(广东路)",
        "沿世纪大道辅路步行285米左转",
        "步行75米",
    ]

    app_names = {"MCP-Amap", "Messages"}

    async def is_successful_async(self, controller: AndroidController) -> float | tuple[float, str]:
        """Check if the task is successful."""
        self._check_is_initialized()

        # Check 1: Verify SMS was sent
        sms_bodies = get_sent_sms_bodies_via_adb(controller, self.RECIPIENT_PHONE)
        if not sms_bodies:
            return 0.0, f"SMS not found sent to {self.RECIPIENT_PHONE}"

        lines = [line.strip() for line in sms_bodies[0].splitlines() if line.strip()]

        if len(lines) < 3:
            return 0.0, f"Expected at least 3 lines in SMS, found {len(lines)}"

        first_line = lines[0]

        required_locations = [
            "上海市徐汇区漕溪北路41号",
            "上海市浦东新区世纪大道100号",
        ]

        for location in required_locations:
            if location not in first_line:
                return 0.0, f"Location '{location}' not found in first line"

            coord = self.LOCATIONS.get(location)
            if coord and coord not in first_line:
                return 0.0, f"Coordinate '{coord}' for '{location}' not found in first line"

        station_names = ["徐家汇", "人民广场", "世纪大道浦东南路"]
        found_stations = [name for name in station_names if name in first_line]

        if len(found_stations) < 2:
            return 0.0, (
                f"Expected at least 2 stations (departure and arrival) in first line, "
                f"found {len(found_stations)}: {found_stations}"
            )

        for station in found_stations:
            coord = self.LOCATIONS.get(station)
            if coord and coord not in first_line:
                return 0.0, f"Coordinate '{coord}' for station '{station}' not found in first line"

        instructions_line = lines[1]

        colon_pos = instructions_line.find("：")
        if colon_pos == -1:
            colon_pos = instructions_line.find(":")
        if colon_pos != -1:
            instructions_text = instructions_line[colon_pos + 1 :].strip()
        else:
            instructions_text = instructions_line.strip()

        instructions = [
            inst.strip() for inst in re.split(r"[，,]+", instructions_text) if inst.strip()
        ]

        if len(instructions) == 0:
            return 0.0, "No walking instructions found in second line"

        instruction_text_combined = " ".join(instructions)

        walking_keywords = ["步行", "到达", "左转", "右转", "沿", "行走", "转"]
        found_keywords = sum(
            1 for keyword in walking_keywords if keyword in instruction_text_combined
        )
        if found_keywords == 0:
            return 0.0, "Walking instructions do not contain any walking-related keywords"

        distance_line = lines[2]

        colon_pos = distance_line.find("：")
        if colon_pos == -1:
            colon_pos = distance_line.find(":")
        if colon_pos != -1:
            distance_str = distance_line[colon_pos + 1 :].strip()
        else:
            distance_str = distance_line.strip()

        distances = []
        for d in re.split(r"[，,]+", distance_str):
            d = d.strip()
            match = re.search(r"(\d+)", d)
            if match:
                distances.append(int(match.group(1)))

        if len(distances) < 2:
            return (
                0.0,
                f"Expected at least 2 distances (walking and transit), found {len(distances)}",
            )

        # Validate distances
        walking_distance = distances[0]
        transit_distance = distances[1] if len(distances) > 1 else 0

        if abs(walking_distance - self.EXPECTED_WALKING_DISTANCE) > 50:
            return 0.0, (
                f"Walking distance mismatch. Expected: {self.EXPECTED_WALKING_DISTANCE}m, "
                f"Got: {walking_distance}m"
            )

        if abs(transit_distance - self.EXPECTED_TRANSIT_DISTANCE) > 500:
            return 0.0, (
                f"Transit distance mismatch. Expected: {self.EXPECTED_TRANSIT_DISTANCE}m, "
                f"Got: {transit_distance}m"
            )

        return 1.0

    def tear_down(self, controller: AndroidController) -> bool:
        super().tear_down(controller)
        return True
