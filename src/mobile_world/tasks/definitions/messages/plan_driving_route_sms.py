"""Plan shortest self-driving sightseeing route in Jiangsu and send SMS with route details."""

import re

from mobile_world.runtime.app_helpers.system import get_sent_sms_bodies_via_adb
from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


class PlanDrivingRouteSmsTask(BaseTask):
    """Plan a shortest self-driving sightseeing route in Jiangsu and send SMS."""

    goal = (
        "Please help me plan exactly 1 self-driving sightseeing shortest path route in Jiangsu that:\n"
        'Starts at "南京市玄武区龙蟠路100号" (Nanjing Railway Station),\n'
        "must visit exactly 3 scenic spots chosen from the following 5 candidates (each visited at most once),\n"
        'and finally ends at "江苏省苏州市姑苏区苏站路27号" (Suzhou Railway Station):\n'
        '1. "南京夫子庙" (Confucius Temple in Nanjing)\n'
        '2. "中山陵" (Sun Yat-sen Mausoleum in Nanjing)\n'
        '3. "无锡鼋头渚风景区" (Yuantouzhu Scenic Area in Wuxi)\n'
        '4. "无锡灵山大佛" (Lingshan Grand Buddha in Wuxi)\n'
        '5. "苏州拙政园" (Humble Administrator\'s Garden in Suzhou)\n'
        "请短信发送下面的内容给我的自驾伙伴Jack 13600136000：\n"
        "把最后选择的路线上的5个地点名称和坐标：[名称：坐标，经度,纬度，逗号分隔]，按实际驾车顺序给出\n "
        "相邻地点之间的驾车距离（米），按驾车顺序计算，逗号分隔\n "
        "总直线距离（米）\n "
    )
    task_tags = {"agent-mcp"}

    RECIPIENT_PHONE = "13600136000"

    # Location coordinates for validation
    LOCATIONS = {
        "南京市玄武区龙蟠路100号": "118.809953,32.070443",
        "南京夫子庙": "118.788899,32.020660",
        "中山陵": "113.528326,22.446988",
        "无锡鼋头渚风景区": "120.227995,31.517799",
        "无锡灵山大佛": "120.311889,31.491064",
        "苏州拙政园": "120.628659,31.324000",
        "江苏省苏州市姑苏区苏站路27号": "120.609745,31.329918",
    }

    # Expected shortest route order
    EXPECTED_ROUTE_ORDER = [
        "南京市玄武区龙蟠路100号",
        "无锡鼋头渚风景区",
        "无锡灵山大佛",
        "苏州拙政园",
        "江苏省苏州市姑苏区苏站路27号",
    ]

    # Expected segment distances (in meters)
    EXPECTED_SEGMENT_DISTANCES = [181346, 11190, 44674, 3961]
    EXPECTED_TOTAL_DISTANCE = 241171  # Sum of segments

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

        # Check 2: Verify first line contains all 5 locations with exact coordinates
        first_line = lines[0]

        # Verify all 5 locations in expected route are present with exact coordinates
        for location in self.EXPECTED_ROUTE_ORDER:
            if location not in first_line:
                return 0.0, f"Location '{location}' not found in first line"
            # Verify exact coordinate match
            coord = self.LOCATIONS.get(location)
            if coord and coord not in first_line:
                return 0.0, f"Coordinate '{coord}' for '{location}' not found in first line"

        # Check 3: Verify second line contains segment distances
        distance_line = lines[1]

        # Extract distances (after colon if present)
        colon_pos = distance_line.find("：")
        if colon_pos == -1:
            colon_pos = distance_line.find(":")
        if colon_pos != -1:
            distance_str = distance_line[colon_pos + 1 :].strip()
        else:
            distance_str = distance_line.strip()

        # Parse distances using comma separator
        distances = []
        for d in re.split(r"[，,]+", distance_str):
            d = d.strip()
            # Remove any non-digit characters except numbers
            d_clean = re.sub(r"[^\d]", "", d)
            if d_clean:
                distances.append(int(d_clean))

        if len(distances) != 4:
            return 0.0, f"Expected 4 segment distances, found {len(distances)}"

        # Validate segment distances against expected (with tolerance)
        for i, (expected_dist, actual_dist) in enumerate(
            zip(self.EXPECTED_SEGMENT_DISTANCES, distances)
        ):
            # Use 5% tolerance for large distances, 500m for smaller ones
            if expected_dist > 10000:
                tolerance = expected_dist * 0.05
            else:
                tolerance = 500

            if abs(actual_dist - expected_dist) > tolerance:
                return 0.0, (
                    f"Segment {i + 1} distance mismatch. Expected: {expected_dist}m, "
                    f"Got: {actual_dist}m (tolerance: {tolerance:.0f}m)"
                )

        # Check 4: Verify third line contains total distance
        total_line = lines[2]

        # Extract total distance
        total_distance_match = re.search(r"[\d,]+", total_line)
        if not total_distance_match:
            return 0.0, "Total distance number not found"

        total_distance_str = total_distance_match.group().replace(",", "")
        total_distance = int(total_distance_str)

        if total_distance != self.EXPECTED_TOTAL_DISTANCE:
            return (
                0.0,
                f"Total distance mismatch. Expected: {self.EXPECTED_TOTAL_DISTANCE}m, Got: {total_distance}m",
            )

        return 1.0

    def tear_down(self, controller: AndroidController) -> bool:
        super().tear_down(controller)
        return True
