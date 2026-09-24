"""Read-only pre-operation report for Noetix Bumi."""

import math
import time
from datetime import datetime, timezone


SOURCE_INTERVALS = {"battery": 1.0, "imu": 0.05, "joints": 0.1}


def _timestamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def _temperatures(source: str, data: dict) -> list[float]:
    if source == "joints":
        raw = [joint.get("temp") for joint in data.get("joints", [])]
    elif source == "battery":
        raw = [data.get("temperature")]
    else:
        return []
    return [float(value) for value in raw
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value)]


def evaluate_health(samples: dict, config: dict, *, motion_interval: float = 0.5,
                    now_monotonic: float | None = None, now_wall: float | None = None) -> dict:
    now_monotonic = time.monotonic() if now_monotonic is None else now_monotonic
    now_wall = time.time() if now_wall is None else now_wall
    limits = config.get("temperature_limits") or {}
    minimum = config.get("battery_min_soc", 20)
    checks = {}

    for source, interval in {**SOURCE_INTERVALS, "motion_state": motion_interval}.items():
        sample = samples.get(source)
        limit = limits.get(source)
        item = {
            "status": "数据不足",
            "data": sample["data"] if sample else None,
            "received_at": _timestamp(sample["received_at"]) if sample else None,
            "age_seconds": None,
            "reasons": [],
            "temperature": {"status": "未判定" if limit is None else "数据不足",
                            "maximum": None, "limit": limit},
        }
        checks[source] = item
        if sample is None:
            item["reasons"].append("尚未收到数据")
            continue

        age = max(0.0, now_monotonic - sample["received_monotonic"])
        item["age_seconds"] = round(age, 3)
        if age > interval * 3:
            item["reasons"].append(f"数据已过期（超过 {interval * 3:g} 秒）")
            continue

        data = sample["data"]
        if not isinstance(data, dict):
            item["reasons"].append("数据格式无效")
            continue
        item["status"] = "正常"

        if source == "battery":
            soc = data.get("soc")
            if not isinstance(soc, (int, float)) or isinstance(soc, bool) or not math.isfinite(soc) or not 0 <= soc <= 100:
                item["status"] = "数据不足"
                item["reasons"].append("电量读数无效")
                continue
            if soc < minimum:
                item["status"] = "异常"
                item["reasons"].append(f"电量 {soc}% 低于 {minimum}%")
            alarm = data.get("alarm")
            if isinstance(alarm, int) and not isinstance(alarm, bool) and alarm != 0:
                item["status"] = "异常"
                item["reasons"].append(f"电池报警码 {alarm}")
        elif source == "imu" and not data.get("quaternion"):
            item["status"] = "数据不足"
            item["reasons"].append("IMU 四元数为空")
            continue
        elif source == "joints" and len(data.get("joints") or []) != 21:
            item["status"] = "数据不足"
            item["reasons"].append("关节读数未包含全部 21 个关节")
            continue
        elif source == "motion_state":
            workmode = data.get("workmode") or {}
            if not data.get("fresh") or not isinstance(workmode, dict) or not workmode:
                item["status"] = "数据不足"
                item["reasons"].append("运动状态读数无效")
                continue
            if workmode.get("protection"):
                item["status"] = "异常"
                item["reasons"].append("机器人处于保护模式")
            faults = data.get("motor_faults") or []
            if faults:
                item["status"] = "异常"
                item["reasons"].append(f"检测到 {len(faults)} 项已识别的电机故障")

        values = _temperatures(source, data)
        if values:
            item["temperature"]["maximum"] = max(values)
        if source not in limits:
            if source in ("battery", "joints"):
                item["temperature"]["reason"] = "温度界限未配置"
            else:
                item["temperature"]["reason"] = "此数据源不提供温度判断"
            continue
        if not values:
            item["temperature"]["status"] = "数据不足"
            item["status"] = "数据不足" if item["status"] == "正常" else item["status"]
            item["reasons"].append("温度读数为空")
            continue
        maximum = max(values)
        if maximum > limit:
            item["temperature"]["status"] = "异常"
            item["status"] = "异常"
            item["reasons"].append(f"最高温度 {maximum:g} 超过 {limit:g}")
        else:
            item["temperature"]["status"] = "正常"

    statuses = {item["status"] for item in checks.values()}
    overall = "异常" if "异常" in statuses else "数据不足" if "数据不足" in statuses else "正常"
    summary = {
        "异常": "已发现预设异常；请查看各项原因。",
        "数据不足": "状态数据不完整或已过期，无法完成检查。",
        "正常": "已启用的检查项未发现异常；这不是运动安全许可。",
    }[overall]
    unassessed = [source for source in ("battery", "joints")
                  if checks[source]["temperature"]["status"] == "未判定"]
    if unassessed:
        summary += " 未配置温度界限的项目未作温度安全判断。"
    return {
        "status": overall,
        "summary": summary,
        "checked_at": _timestamp(now_wall),
        "checks": checks,
        "temperature_unassessed": unassessed,
        "unsupported": {"mainboard": "Bumi 驱动未提供独立主板状态数据"},
    }


class HealthCheckPlugin:
    PREFIX = "health_check"

    def __init__(self, plugin_config: dict, state_plugin=None, motion_state_plugin=None):
        self._config = plugin_config
        self._state_plugin = state_plugin
        self._motion_state_plugin = motion_state_plugin
        minimum = plugin_config.get("battery_min_soc", 20)
        if not isinstance(minimum, (int, float)) or isinstance(minimum, bool) or not math.isfinite(minimum) or not 0 <= minimum <= 100:
            raise ValueError("health_check.battery_min_soc must be between 0 and 100")
        limits = plugin_config.get("temperature_limits") or {}
        if not isinstance(limits, dict) or any(
            key not in ("battery", "joints") or not isinstance(value, (int, float))
            or isinstance(value, bool) or not math.isfinite(value)
            for key, value in limits.items()
        ):
            raise ValueError("health_check.temperature_limits must contain finite battery/joints limits")

    def get_tool(self) -> dict:
        return {
            "name": "health_check", "type": "actuator", "multiInstance": False,
            "description": "Read-only Bumi pre-operation report: battery, IMU, joints, protection mode and documented motor faults. Does not move or authorize movement.",
            "inputSchema": {"type": "object",
                            "properties": {"action": {"type": "string", "enum": ["check"],
                                                      "description": "Generate a health report"}},
                            "required": ["action"]},
        }

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def dispatch(self, action: str, args: dict) -> dict | None:
        if action in ("start", "info"):
            return {"state": "ready"}
        if action == "stop":
            return {"state": "idle"}
        if action == "check":
            samples = self._state_plugin.health_snapshot() if self._state_plugin else {}
            motion = self._motion_state_plugin.health_snapshot() if self._motion_state_plugin else None
            if motion:
                samples["motion_state"] = motion
            interval = self._motion_state_plugin.poll_interval_s if self._motion_state_plugin else 0.5
            return evaluate_health(samples, self._config, motion_interval=interval)
        return None
