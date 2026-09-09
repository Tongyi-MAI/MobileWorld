"""Plan cycling route in Hangzhou and send SMS with route details."""

import re

from mobile_world.runtime.app_helpers.system import get_sent_sms_bodies_via_adb
from mobile_world.runtime.controller import AndroidController
from mobile_world.tasks.base import BaseTask


class PlanCyclingRouteSmsTask(BaseTask):
    """Plan a cycling route in Hangzhou that passes through 4 landmarks and send SMS."""

    goal = (
        "Please help me plan exactly 1 cycling route in Hangzhou that: "
        'Starts and ends at "杭州东站 (Hangzhou East Railway Station)". '
        "Passes through exactly the following 4 landmarks in Hangzhou, in any order:\n"
        '1. "保俶塔 (Baochu Pagoda)"\n'
        '2. "雷峰塔 (Leifeng Pagoda)"\n'
        '3. "杭州杨公堤 (Yanggong Causeway)"\n'
        '4. "杭州奥林匹克体育中心主体育场 (Hangzhou Olympic Sports Center Stadium)"\n'
        "Forms a loop with the following strict constraints on straight-line distances between consecutive waypoints "
        "(including the final segment back to the start):\n"
        "Each segment between consecutive points must be between 3 km and 15 km.\n"
        "The total riding distance of the whole loop must be between 20 km and 42 km\n"
        "请短信发送下面的内容给我的骑行伙伴mike 18756627900:"
        "5个地点名称和坐标：[地点：坐标，逗号分隔]\\n "
        "骑行的路线：从起点到终点，按顺序组织地点的名字，逗号分隔\\n "
        "相邻点之间的骑车距离，按骑行顺序计算，逗号分隔 \\n "
        "总路线的距离"
    )
    task_tags = {"agent-mcp", "lang-en"}

    RECIPIENT_PHONE = "18756627900"

    # Landmark coordinates for validation
    LANDMARKS = {
        "杭州东站": "120.212600,30.290851",
        "杭州保俶塔": "120.209903,30.246566",
        "雷峰塔": "120.209903,30.246566",
        "杭州杨公堤": "120.132686,30.240079",
        "杭州奥林匹克体育中心主体育场": "120.230349,30.228173",
    }

    # Expected distances between landmarks (in meters, from user's validation data)
    EXPECTED_DISTANCES = {
        ("杭州东站", "杭州保俶塔"): 6577,
        ("杭州东站", "雷峰塔"): 6577,
        ("杭州东站", "杭州杨公堤"): 11893,
        ("杭州东站", "杭州奥林匹克体育中心主体育场"): 12052,
        ("杭州保俶塔", "雷峰塔"): 1,
        ("杭州保俶塔", "杭州杨公堤"): 10498,
        ("杭州保俶塔", "杭州奥林匹克体育中心主体育场"): 5728,
        ("雷峰塔", "杭州杨公堤"): 10498,
        ("雷峰塔", "杭州奥林匹克体育中心主体育场"): 5923,
        ("杭州杨公堤", "杭州奥林匹克体育中心主体育场"): 16352,
    }

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

        # Check 2: Verify first line contains all 5 landmarks with correct coordinates
        first_line = lines[0]
        for name, coord in self.LANDMARKS.items():
            if name not in first_line:
                return 0.0, f"Landmark name '{name}' not found in first line"
            if coord not in first_line:
                return 0.0, f"Coordinate '{coord}' for '{name}' not found in first line"

        # Check 3: Verify second line is the route with 6 points containing all 5 landmarks
        route_line = lines[1]

        # Extract route (after colon)
        colon_pos = route_line.find("：")
        if colon_pos == -1:
            colon_pos = route_line.find(":")
        if colon_pos == -1:
            return 0.0, "Route separator not found"

        route_text = route_line[colon_pos + 1 :].strip()
        # Remove brackets if present
        route_text = route_text.strip("【】[]")

        route_parts = re.split(r"[，,]+", route_text)
        route_order = [part.strip() for part in route_parts if part.strip()]

        if len(route_order) != 6:
            return 0.0, f"Route must have 6 points, found {len(route_order)}: {route_order}"

        # Verify all 5 landmarks are in route
        route_set = set(route_order)
        required_landmarks = set(self.LANDMARKS.keys())
        if route_set != required_landmarks:
            missing = required_landmarks - route_set
            return 0.0, f"Route missing landmarks: {missing}"

        # Check 4: Verify third line contains segment distances and validate against EXPECTED_DISTANCES
        distance_line = lines[2]
        if "相邻点" not in distance_line:
            return 0.0, "Segment distances line not found in third line"

        # Extract distances
        colon_pos = distance_line.find("：")
        if colon_pos == -1:
            colon_pos = distance_line.find(":")
        if colon_pos == -1:
            return 0.0, "Distance separator not found"

        distance_str = distance_line[colon_pos + 1 :].strip()
        segment_distances = [int(d.strip()) for d in distance_str.split(",") if d.strip().isdigit()]

        if len(segment_distances) != 5:
            return 0.0, f"Expected 5 segment distances, found {len(segment_distances)}"

        # Validate each segment distance using EXPECTED_DISTANCES
        for i in range(len(route_parts) - 1):
            point1 = route_parts[i]
            point2 = route_parts[i + 1]

            # Get expected distance from EXPECTED_DISTANCES
            expected_dist = self.EXPECTED_DISTANCES.get((point1, point2))
            if expected_dist is None:
                expected_dist = self.EXPECTED_DISTANCES.get((point2, point1))

            if expected_dist is None:
                return 0.0, f"Distance not found in EXPECTED_DISTANCES for {point1} -> {point2}"

            # Check if reported distance matches expected distance
            reported_dist = segment_distances[i]
            if reported_dist != expected_dist:
                return 0.0, (
                    f"Segment {i + 1} ({point1} -> {point2}): "
                    f"reported distance {reported_dist}m does not match expected {expected_dist}m"
                )

            # Check segment distance constraint: 3-10 km
            if expected_dist < 3000 or expected_dist > 15000:
                return 0.0, (
                    f"Segment {i + 1} ({point1} -> {point2}): "
                    f"distance {expected_dist / 1000:.2f} km is not between 3-10 km"
                )

        # Check 5: Verify fourth line contains total distance
        total_line = lines[3]
        if "总" not in total_line or "距离" not in total_line:
            return 0.0, "Total distance line not found in fourth line"

        # Extract total distance
        total_distance_match = re.search(r"[\d.]+", total_line)
        if not total_distance_match:
            return 0.0, "Total distance number not found"

        total_distance = int(float(total_distance_match.group()))

        # Calculate expected total distance from segment distances
        expected_total = sum(segment_distances)
        if total_distance != expected_total:
            return 0.0, (
                f"Total distance {total_distance}m does not match sum of segments {expected_total}m"
            )

        # Check total distance constraint: 20-40 km
        if total_distance < 20000 or total_distance > 42000:
            return 0.0, f"Total distance {total_distance / 1000:.2f} km is not between 20-40 km"

        return 1.0

    def tear_down(self, controller: AndroidController) -> bool:
        super().tear_down(controller)
        return True
