import asyncio

import pytest

from mobile_world.tasks.definitions.messages import (
    plan_commute_route_sms,
    plan_cycling_route_sms,
    plan_driving_route_sms,
    plan_taxi_route_sms,
)


@pytest.mark.parametrize(
    ("task_module", "task_class", "expected_line_count"),
    [
        (plan_taxi_route_sms, plan_taxi_route_sms.PlanTaxiRouteSmsTask, 4),
        (plan_driving_route_sms, plan_driving_route_sms.PlanDrivingRouteSmsTask, 3),
        (plan_cycling_route_sms, plan_cycling_route_sms.PlanCyclingRouteSmsTask, 4),
        (plan_commute_route_sms, plan_commute_route_sms.PlanCommuteRouteSmsTask, 3),
    ],
)
def test_route_sms_verifiers_receive_message_body(
    monkeypatch, task_module, task_class, expected_line_count
):
    monkeypatch.setattr(
        task_module,
        "get_sent_sms_bodies_via_adb",
        lambda controller, phone_number: ["one line"],
    )
    task = task_class()
    task.initialized = True

    result = asyncio.run(task.is_successful_async(object()))

    assert result == (
        0.0,
        f"Expected at least {expected_line_count} lines in SMS, found 1",
    )


def _taxi_sms_body(task):
    return "\n".join(
        [
            "，".join(f"{name}：{coordinate}" for name, coordinate in task.LOCATIONS.items()),
            "路线：" + "，".join(task.EXPECTED_ROUTE_ORDER),
            "分段距离：" + "，".join(str(value) for value in task.EXPECTED_SEGMENT_DISTANCES),
            f"总距离：{task.EXPECTED_TOTAL_DISTANCE}",
        ]
    )


def _driving_sms_body(task):
    return "\n".join(
        [
            "，".join(f"{name}：{task.LOCATIONS[name]}" for name in task.EXPECTED_ROUTE_ORDER),
            "分段距离：" + "，".join(str(value) for value in task.EXPECTED_SEGMENT_DISTANCES),
            f"总距离：{task.EXPECTED_TOTAL_DISTANCE}",
        ]
    )


def _cycling_sms_body(task):
    route = [
        "杭州东站",
        "杭州保俶塔",
        "杭州奥林匹克体育中心主体育场",
        "雷峰塔",
        "杭州杨公堤",
        "杭州东站",
    ]
    distances = [6577, 5728, 5923, 10498, 11893]
    return "\n".join(
        [
            "，".join(f"{name}：{coordinate}" for name, coordinate in task.LANDMARKS.items()),
            "路线：" + "，".join(route),
            "相邻点距离：" + ",".join(str(value) for value in distances),
            f"总距离：{sum(distances)}",
        ]
    )


def _commute_sms_body(task):
    locations = [
        "上海市徐汇区漕溪北路41号",
        "上海市浦东新区世纪大道100号",
        "徐家汇",
        "人民广场",
    ]
    return "\n".join(
        [
            "，".join(f"{name}：{task.LOCATIONS[name]}" for name in locations),
            "步行路线：步行24米向右前方行走，步行21米左转",
            f"距离：{task.EXPECTED_WALKING_DISTANCE},{task.EXPECTED_TRANSIT_DISTANCE}",
        ]
    )


@pytest.mark.parametrize(
    ("task_module", "task_class", "body_factory"),
    [
        (plan_taxi_route_sms, plan_taxi_route_sms.PlanTaxiRouteSmsTask, _taxi_sms_body),
        (
            plan_driving_route_sms,
            plan_driving_route_sms.PlanDrivingRouteSmsTask,
            _driving_sms_body,
        ),
        (
            plan_cycling_route_sms,
            plan_cycling_route_sms.PlanCyclingRouteSmsTask,
            _cycling_sms_body,
        ),
        (
            plan_commute_route_sms,
            plan_commute_route_sms.PlanCommuteRouteSmsTask,
            _commute_sms_body,
        ),
    ],
)
def test_route_sms_verifiers_can_score_valid_body(
    monkeypatch, task_module, task_class, body_factory
):
    task = task_class()
    task.initialized = True
    sms_body = body_factory(task)
    monkeypatch.setattr(
        task_module,
        "get_sent_sms_bodies_via_adb",
        lambda controller, phone_number: [sms_body],
    )

    result = asyncio.run(task.is_successful_async(object()))

    assert result == 1.0
