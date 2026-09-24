"""Bumi health verdicts use cached readings and never call hardware."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from health_check import HealthCheckPlugin, evaluate_health


NOW = 100.0
WALL = 1_700_000_000.0


def samples():
    readings = {
        "battery": {"soc": 65, "soh": 95, "temperature": 32, "alarm": 0},
        "imu": {"quaternion": [0, 0, 0, 1], "angular_vel": [0, 0, 0]},
        "joints": {"joints": [{"idx": i, "temp": 40 + i % 3} for i in range(21)]},
        "motion_state": {"fresh": True, "workmode": {"code": 2, "protection": False},
                         "motor_faults": []},
    }
    return {name: {"data": data, "received_monotonic": NOW - 0.01,
                   "received_at": WALL - 0.01} for name, data in readings.items()}


def check(value, config=None):
    return evaluate_health(value, config or {"battery_min_soc": 20},
                           now_monotonic=NOW, now_wall=WALL)


def test_healthy_report_preserves_readings_and_identifies_limits():
    report = check(samples())
    assert report["status"] == "正常"
    assert report["checks"]["battery"]["data"]["soc"] == 65
    assert report["checks"]["joints"]["temperature"]["maximum"] == 42
    assert report["temperature_unassessed"] == ["battery", "joints"]
    assert "mainboard" in report["unsupported"]
    assert "不是运动安全许可" in report["summary"]


def test_low_battery_and_bms_alarm_are_reported():
    value = samples()
    value["battery"]["data"].update(soc=19, alarm=4)
    report = check(value)
    assert report["status"] == "异常"
    assert "19%" in report["checks"]["battery"]["reasons"][0]
    assert "4" in report["checks"]["battery"]["reasons"][1]


def test_protection_and_motor_faults_are_reported():
    value = samples()
    value["motion_state"]["data"]["workmode"]["protection"] = True
    value["motion_state"]["data"]["motor_faults"] = [{"motor_id": 1, "error": 11}]
    report = check(value)
    assert report["status"] == "异常"
    assert len(report["checks"]["motion_state"]["reasons"]) == 2


def test_missing_and_stale_data_never_report_normal():
    value = samples()
    del value["imu"]
    assert check(value)["status"] == "数据不足"
    value = samples()
    value["motion_state"]["received_monotonic"] = NOW - 1.51
    assert check(value)["checks"]["motion_state"]["status"] == "数据不足"


def test_abnormal_overrides_missing_data():
    value = samples()
    value["battery"]["data"]["soc"] = 5
    del value["imu"]
    assert check(value)["status"] == "异常"


def test_configured_temperature_limit_and_missing_reading():
    report = check(samples(), {"temperature_limits": {"joints": 41}})
    assert report["status"] == "异常"
    assert report["checks"]["joints"]["temperature"]["status"] == "异常"
    value = samples()
    value["battery"]["data"].pop("temperature")
    report = check(value, {"temperature_limits": {"battery": 60}})
    assert report["status"] == "数据不足"


def test_plugin_lifecycle_and_no_hardware_actions():
    import time

    class State:
        def health_snapshot(self):
            result = samples()
            for item in result.values():
                item["received_monotonic"] = time.monotonic()
            return {key: result[key] for key in ("battery", "imu", "joints")}

    class Motion:
        poll_interval_s = 0.5

        def health_snapshot(self):
            result = samples()["motion_state"]
            result["received_monotonic"] = time.monotonic()
            return result

    plugin = HealthCheckPlugin({"battery_min_soc": 20}, State(), Motion())
    assert plugin.get_tool()["inputSchema"]["properties"]["action"]["enum"] == ["check"]
    assert plugin.dispatch("start", {}) == {"state": "ready"}
    assert plugin.dispatch("check", {})["status"] == "正常"
    assert plugin.dispatch("stop", {}) == {"state": "idle"}


def test_invalid_thresholds_fail_at_startup():
    with pytest.raises(ValueError):
        HealthCheckPlugin({"battery_min_soc": 120})
    with pytest.raises(ValueError):
        HealthCheckPlugin({"temperature_limits": {"mainboard": 50}})
