"""
IRIS system-intel router.

Answers machine-state questions directly from local system resources so IRIS
does not need to ask a cloud model about the machine it is already running on.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import time
from typing import Any, Optional

from core.subprocess_utils import hidden_process_kwargs


BATTERY_STATUS_MAP = {
    1: "discharging",
    2: "plugged in",
    3: "fully charged",
    4: "low",
    5: "critical",
    6: "charging",
    7: "charging",
    8: "charging",
    9: "charging",
    11: "partially charged",
}


class SystemIntel:
    def __init__(self) -> None:
        self._cache_ttl_seconds = 15
        self._cache: dict[str, tuple[float, str]] = {}

    def answer_query(self, query: str) -> Optional[str]:
        lowered = (query or "").lower().strip()
        if not lowered:
            return None

        handlers = [
            ("battery", self._is_battery_query, self._answer_battery_query),
            ("storage", self._is_storage_query, lambda: self._answer_storage_query(query)),
            ("memory", self._is_memory_query, self._answer_memory_query),
            ("cpu", self._is_cpu_query, self._answer_cpu_query),
            ("performance", self._is_performance_query, self._answer_performance_query),
            ("hostname", self._is_hostname_query, self._answer_hostname_query),
            ("os", self._is_os_query, self._answer_os_query),
            ("network", self._is_network_query, lambda: self._answer_network_query(query)),
        ]

        for cache_prefix, matcher, handler in handlers:
            if not matcher(lowered):
                continue
            cache_key = f"{cache_prefix}:{lowered}"
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached
            answer = handler()
            if answer:
                self._cache_put(cache_key, answer)
            return answer

        return None

    def _is_battery_query(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in ["battery", "charge level", "power level", "charging", "plugged in"]
        )

    def _is_storage_query(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in ["disk space", "storage", "free space", "space left", "drive space"]
        )

    def _is_memory_query(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in ["memory usage", "ram usage", "available memory", "free memory", "ram left"]
        )

    def _is_hostname_query(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in ["computer name", "hostname", "device name", "machine name"]
        )

    def _is_cpu_query(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in [
                "cpu usage",
                "processor usage",
                "cpu load",
                "processor load",
                "what's using my cpu",
                "what is using my cpu",
                "using my processor",
                "cpu right now",
            ]
        )

    def _is_performance_query(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in [
                "why is my computer slow",
                "why is my pc slow",
                "why is my laptop slow",
                "what's slowing down my computer",
                "what is slowing down my computer",
                "why is this machine slow",
                "why is the system slow",
            ]
        )

    def _is_os_query(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in ["operating system", "windows version", "os version", "what os", "what system am i on"]
        )

    def _is_network_query(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in [
                "am i online",
                "internet connection",
                "network status",
                "wifi status",
                "wi-fi status",
                "ip address",
                "local ip",
                "network name",
            ]
        )

    def _answer_battery_query(self) -> str:
        payload = self._run_powershell_json(
            """
$battery = Get-CimInstance Win32_Battery | Select-Object -First 1 EstimatedChargeRemaining, BatteryStatus
if ($battery) {
  $battery | ConvertTo-Json -Compress
}
"""
        )
        if not payload:
            return "This system is not reporting a battery right now."

        charge = payload.get("EstimatedChargeRemaining")
        status_code = int(payload.get("BatteryStatus") or 0)
        status_text = BATTERY_STATUS_MAP.get(status_code, "available")
        if charge is None:
            return f"Battery status is {status_text}."
        return f"Battery is at {int(charge)}% and currently {status_text}."

    def _answer_storage_query(self, query: str) -> str:
        drive_match = re.search(r"\b([a-z]):", query, flags=re.IGNORECASE)
        drive = f"{drive_match.group(1).upper()}:\\\\" if drive_match else self._default_drive()
        usage = shutil.disk_usage(drive)
        total_gb = usage.total / (1024 ** 3)
        free_gb = usage.free / (1024 ** 3)
        used_percent = ((usage.total - usage.free) / usage.total) * 100 if usage.total else 0
        return (
            f"{drive} has {free_gb:.1f} GB free out of {total_gb:.1f} GB total "
            f"({used_percent:.0f}% used)."
        )

    def _answer_memory_query(self) -> str:
        payload = self._run_powershell_json(
            """
Get-CimInstance Win32_OperatingSystem |
  Select-Object FreePhysicalMemory, TotalVisibleMemorySize |
  ConvertTo-Json -Compress
"""
        )
        if not payload:
            return "I couldn't read memory usage from the local system right now."

        free_kb = float(payload.get("FreePhysicalMemory") or 0)
        total_kb = float(payload.get("TotalVisibleMemorySize") or 0)
        if total_kb <= 0:
            return "I couldn't read memory usage from the local system right now."

        free_gb = free_kb / (1024 ** 2)
        total_gb = total_kb / (1024 ** 2)
        used_percent = ((total_kb - free_kb) / total_kb) * 100
        return (
            f"Memory usage is about {used_percent:.0f}% used. "
            f"{free_gb:.1f} GB free out of {total_gb:.1f} GB."
        )

    def _answer_cpu_query(self) -> str:
        payload = self._read_performance_snapshot()
        if not payload:
            return "I couldn't read current CPU usage from the local system right now."

        cpu_percent = self._safe_float(payload.get("CpuPercent"))
        top = self._format_top_processes(payload.get("TopCpu"))
        if cpu_percent is None:
            return "I couldn't read current CPU usage from the local system right now."

        message = f"CPU usage is about {cpu_percent:.0f}% right now."
        if top:
            message += f" Top CPU activity: {top}."
        return message

    def _answer_performance_query(self) -> str:
        payload = self._read_performance_snapshot()
        if not payload:
            return "I couldn't read local performance counters right now."

        cpu_percent = self._safe_float(payload.get("CpuPercent"))
        free_gb, total_gb, used_percent = self._memory_summary_from_payload(payload)
        top = self._format_top_processes(payload.get("TopCpu"))

        bits = []
        if cpu_percent is not None:
            bits.append(f"CPU is around {cpu_percent:.0f}%")
        if used_percent is not None and free_gb is not None and total_gb is not None:
            bits.append(f"memory is about {used_percent:.0f}% used with {free_gb:.1f} GB free out of {total_gb:.1f} GB")
        if top:
            bits.append(f"top CPU activity looks like {top}")

        if not bits:
            return "I couldn't find a clear local performance bottleneck right now."
        return "Right now, " + "; ".join(bits) + "."

    def _answer_hostname_query(self) -> str:
        name = os.getenv("COMPUTERNAME") or platform.node() or "unknown"
        return f"This machine is named {name}."

    def _answer_os_query(self) -> str:
        system = platform.system() or "Unknown OS"
        release = platform.release() or ""
        version = platform.version() or ""
        machine = platform.machine() or ""
        return f"This machine is running {system} {release} on {machine}. Version: {version}."

    def _answer_network_query(self, query: str) -> str:
        profile = self._run_powershell_json(
            """
Get-NetConnectionProfile |
  Select-Object -First 1 Name, NetworkCategory, IPv4Connectivity, IPv6Connectivity |
  ConvertTo-Json -Compress
"""
        ) or {}

        local_ip = self._best_local_ip()
        name = str(profile.get("Name") or "unknown network").strip()
        category = str(profile.get("NetworkCategory") or "unknown").strip()
        ipv4 = str(profile.get("IPv4Connectivity") or "unknown").strip()
        online = self._internet_reachable()

        lowered = (query or "").lower()
        if "ip" in lowered:
            if local_ip:
                return f"Your local IPv4 address is {local_ip}."
            return "I couldn't determine a local IPv4 address right now."

        online_text = "online" if online else "offline"
        if local_ip:
            return (
                f"Network looks {online_text}. Connected to {name} ({category}), "
                f"IPv4 status {ipv4}, local IP {local_ip}."
            )
        return f"Network looks {online_text}. Connected to {name} ({category}), IPv4 status {ipv4}."

    def _read_performance_snapshot(self) -> Optional[dict[str, Any]]:
        return self._run_powershell_json(
            r"""
$cpu = (Get-Counter '\Processor(_Total)\% Processor Time').CounterSamples |
  Select-Object -First 1
$topCpu = (Get-Counter '\Process(*)\% Processor Time').CounterSamples |
  Where-Object { $_.InstanceName -and $_.InstanceName -notmatch '^(idle|_total)$' } |
  Sort-Object CookedValue -Descending |
  Select-Object -First 5 @{Name='Name';Expression={$_.InstanceName}}, @{Name='CpuPercent';Expression={[math]::Round($_.CookedValue / [Environment]::ProcessorCount, 1)}}
$memory = Get-CimInstance Win32_OperatingSystem |
  Select-Object FreePhysicalMemory, TotalVisibleMemorySize

[PSCustomObject]@{
  CpuPercent = [math]::Round($cpu.CookedValue, 1)
  TopCpu = $topCpu
  FreePhysicalMemory = $memory.FreePhysicalMemory
  TotalVisibleMemorySize = $memory.TotalVisibleMemorySize
} | ConvertTo-Json -Compress -Depth 4
"""
        )

    def _memory_summary_from_payload(self, payload: dict[str, Any]) -> tuple[Optional[float], Optional[float], Optional[float]]:
        free_kb = self._safe_float(payload.get("FreePhysicalMemory"))
        total_kb = self._safe_float(payload.get("TotalVisibleMemorySize"))
        if free_kb is None or total_kb is None or total_kb <= 0:
            return None, None, None
        free_gb = free_kb / (1024 ** 2)
        total_gb = total_kb / (1024 ** 2)
        used_percent = ((total_kb - free_kb) / total_kb) * 100
        return free_gb, total_gb, used_percent

    def _format_top_processes(self, value: Any) -> str:
        if not isinstance(value, list):
            return ""

        entries: list[str] = []
        for item in value[:3]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("Name") or "").strip()
            cpu_percent = self._safe_float(item.get("CpuPercent"))
            if not name or cpu_percent is None or cpu_percent <= 0:
                continue
            clean_name = re.sub(r"#\d+$", "", name)
            entries.append(f"{clean_name} at {cpu_percent:.0f}%")
        return ", ".join(entries)

    def _run_powershell_json(self, script: str) -> Optional[dict[str, Any]]:
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script.strip()],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
                **hidden_process_kwargs(),
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

        if isinstance(payload, list):
            return payload[0] if payload else None
        if isinstance(payload, dict):
            return payload
        return None

    def _best_local_ip(self) -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
        except Exception:
            return ""

    def _internet_reachable(self) -> bool:
        try:
            with socket.create_connection(("1.1.1.1", 53), timeout=1.5):
                return True
        except OSError:
            return False

    def _default_drive(self) -> str:
        anchor = Path.cwd().anchor
        if anchor:
            return anchor
        return os.getenv("SystemDrive", "C:") + "\\"

    def _safe_float(self, value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _cache_get(self, key: str) -> Optional[str]:
        cached = self._cache.get(key)
        if not cached:
            return None
        stored_at, value = cached
        if time.time() - stored_at > self._cache_ttl_seconds:
            self._cache.pop(key, None)
            return None
        return value

    def _cache_put(self, key: str, value: str) -> None:
        self._cache[key] = (time.time(), value)
