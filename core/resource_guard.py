"""
IRIS local resource guard.

Keeps local-first features from pushing too hard on the machine when free
memory is low or the laptop is running on low battery.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import subprocess
import time
from typing import Optional

from config import Config


BATTERY_AC_STATUSES = {2, 3, 6, 7, 8, 9, 11}


@dataclass
class ResourceSnapshot:
    free_memory_gb: float
    total_memory_gb: float
    battery_percent: Optional[int]
    battery_status: Optional[int]

    @property
    def on_ac_power(self) -> bool:
        if self.battery_status is None:
            return True
        return self.battery_status in BATTERY_AC_STATUSES


class ResourceGuard:
    def __init__(self) -> None:
        self._cache: tuple[float, ResourceSnapshot | None] = (0.0, None)

    def allows_local_tts(self) -> tuple[bool, str]:
        return self._evaluate(
            min_battery=int(getattr(Config, "LOCAL_RESOURCE_MIN_BATTERY_PERCENT", 15)),
            min_free_memory=float(getattr(Config, "LOCAL_RESOURCE_MIN_FREE_MEMORY_GB", 1.25)),
        )

    def allows_local_stt(self) -> tuple[bool, str]:
        return self._evaluate(
            min_battery=max(10, int(getattr(Config, "LOCAL_RESOURCE_MIN_BATTERY_PERCENT", 15)) - 2),
            min_free_memory=max(0.9, float(getattr(Config, "LOCAL_RESOURCE_MIN_FREE_MEMORY_GB", 1.25)) - 0.15),
        )

    def allows_local_geo(self) -> tuple[bool, str]:
        return self._evaluate(
            min_battery=int(getattr(Config, "LOCAL_RESOURCE_MIN_BATTERY_PERCENT_FOR_GEO", 8)),
            min_free_memory=0.75,
        )

    def snapshot(self) -> Optional[ResourceSnapshot]:
        now = time.time()
        ttl = max(5, int(getattr(Config, "LOCAL_RESOURCE_SAMPLE_TTL_SECONDS", 20)))
        cached_at, cached_value = self._cache
        if cached_value is not None and (now - cached_at) <= ttl:
            return cached_value

        snapshot = self._read_snapshot()
        self._cache = (now, snapshot)
        return snapshot

    def _evaluate(self, min_battery: int, min_free_memory: float) -> tuple[bool, str]:
        if not getattr(Config, "LOCAL_RESOURCE_GUARD_ENABLED", True):
            return True, ""

        snapshot = self.snapshot()
        if snapshot is None:
            return True, ""

        if snapshot.free_memory_gb < min_free_memory:
            return False, f"free memory is low ({snapshot.free_memory_gb:.1f} GB)"

        if (
            snapshot.battery_percent is not None
            and not snapshot.on_ac_power
            and snapshot.battery_percent < min_battery
        ):
            return False, f"battery is low ({snapshot.battery_percent}%)"

        return True, ""

    def _read_snapshot(self) -> Optional[ResourceSnapshot]:
        script = """
$os = Get-CimInstance Win32_OperatingSystem | Select-Object FreePhysicalMemory, TotalVisibleMemorySize
$battery = Get-CimInstance Win32_Battery | Select-Object -First 1 EstimatedChargeRemaining, BatteryStatus
[PSCustomObject]@{
  free_memory_gb = if ($os.FreePhysicalMemory) { [math]::Round($os.FreePhysicalMemory / 1MB, 2) } else { $null }
  total_memory_gb = if ($os.TotalVisibleMemorySize) { [math]::Round($os.TotalVisibleMemorySize / 1MB, 2) } else { $null }
  battery_percent = $battery.EstimatedChargeRemaining
  battery_status = $battery.BatteryStatus
} | ConvertTo-Json -Compress
""".strip()

        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
        except Exception:
            return None

        output = (completed.stdout or "").strip()
        if not output:
            return None

        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None

        free_memory = payload.get("free_memory_gb")
        total_memory = payload.get("total_memory_gb")
        if free_memory is None or total_memory is None:
            return None

        battery_percent = payload.get("battery_percent")
        battery_status = payload.get("battery_status")
        return ResourceSnapshot(
            free_memory_gb=float(free_memory),
            total_memory_gb=float(total_memory),
            battery_percent=int(battery_percent) if battery_percent is not None else None,
            battery_status=int(battery_status) if battery_status is not None else None,
        )
