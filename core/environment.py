"""
IRIS live environment data.

Provides deterministic location and weather answers so IRIS does not guess
about current conditions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Callable, Optional

import requests

from config import Config
from core.resource_guard import ResourceGuard


WEATHER_CODE_MAP = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


@dataclass
class LocationSnapshot:
    display_name: str
    city: str
    region: str
    country: str
    latitude: float
    longitude: float
    timezone: str
    source: str
    approximate: bool = False
    accuracy_m: Optional[float] = None


@dataclass
class WeatherSnapshot:
    temperature_c: float
    apparent_temperature_c: float
    humidity_percent: float
    precipitation_mm: float
    wind_speed_kmh: float
    wind_direction_deg: float
    weather_code: int
    observed_at: str
    source: str = "Open-Meteo"
    fetched_at: str = ""


class EnvironmentIntel:
    def __init__(self, cache_file: Path | str | None = None) -> None:
        self._cache_ttl_seconds = 300
        self._location_cache: dict[str, tuple[float, object]] = {}
        self._weather_cache: dict[str, tuple[float, object]] = {}
        self._http_headers = {"User-Agent": "IRIS/1.0"}
        self.resource_guard = ResourceGuard()
        self._persistent_cache_file = self._resolve_cache_file(cache_file)
        self._persistent_cache = self._load_persistent_cache()

    def answer_query(self, query: str) -> Optional[str]:
        lowered = (query or "").lower().strip()
        if not lowered:
            return None

        if self._is_time_query(lowered):
            return self._answer_time_query()
        if self._is_weather_query(lowered):
            return self._answer_weather_query(query)
        if self._is_location_query(lowered):
            return self._answer_location_query()
        return None

    def _is_weather_query(self, lowered: str) -> bool:
        blocked_terms = [
            "cpu",
            "gpu",
            "processor",
            "server",
            "engine",
            "fever",
            "body temperature",
        ]
        if any(term in lowered for term in blocked_terms):
            return False

        if "weather" in lowered or "forecast" in lowered:
            return True

        phrase_hits = [
            "outside",
            "is it raining",
            "is it snowing",
            "how hot is it",
            "how cold is it",
            "current temperature",
            "temperature outside",
            "humidity outside",
            "wind outside",
        ]
        if any(phrase in lowered for phrase in phrase_hits):
            return True

        if any(token in lowered for token in ["rain", "raining", "snow", "snowing"]):
            return True

        if "temperature" in lowered:
            return bool(re.search(r"\btemperature\b(?:\s+(?:in|for|at)\b|$)", lowered)) or any(
                marker in lowered for marker in ["right now", "currently", "today"]
            )

        if "degrees" in lowered:
            return any(marker in lowered for marker in ["outside", "right now", "today", " in ", " at "])

        if "humidity" in lowered or "wind" in lowered:
            return any(marker in lowered for marker in ["outside", "right now", "today", " in ", " at "])

        return False

    def _is_location_query(self, lowered: str) -> bool:
        phrases = [
            "where am i",
            "my location",
            "current location",
            "where are we",
            "my coordinates",
            "current coordinates",
            "gps location",
            "latitude",
            "longitude",
        ]
        return any(phrase in lowered for phrase in phrases)

    def _is_time_query(self, lowered: str) -> bool:
        phrases = [
            "what time is it",
            "what's the time",
            "current time",
            "time right now",
            "local time",
            "what's today's date",
            "what is today's date",
            "what is the date",
            "what's the date",
            "current date",
            "what day is it",
            "today's date",
            "my timezone",
            "what timezone",
            "which timezone",
        ]
        return any(phrase in lowered for phrase in phrases)

    def _answer_time_query(self) -> str:
        now = datetime.now().astimezone()
        timezone_name = now.tzname() or "local time"
        return f"It's {now.strftime('%H:%M')} on {now.strftime('%A, %B %d, %Y')} in {timezone_name}."

    def _answer_weather_query(self, query: str) -> Optional[str]:
        explicit_location = self._extract_location_name(query)
        if explicit_location:
            location = self.resolve_named_location(explicit_location)
        else:
            location = self.resolve_current_location()

        if location is None:
            return (
                "I couldn't resolve a reliable location for that weather check yet. "
                "Ask with a city name, or set IRIS_LOCATION_NAME or IRIS_LATITUDE and IRIS_LONGITUDE."
            )

        weather, cached = self.get_current_weather(location)
        if weather is None:
            return (
                f"I couldn't fetch live weather for {location.display_name} right now, "
                "and I don't have a cached weather snapshot yet."
            )

        return self._format_weather_summary(
            location,
            weather,
            cached=cached,
            location_is_approximate=(not explicit_location and location.approximate),
        )

    def _format_weather_summary(
        self,
        location: LocationSnapshot,
        weather: WeatherSnapshot,
        cached: bool,
        location_is_approximate: bool,
    ) -> str:
        if cached:
            prefix = f"Last synced weather for {location.display_name}: "
        else:
            prefix = f"{location.display_name} right now: "

        summary = (
            f"{prefix}"
            f"{weather.temperature_c:.0f}°C, feels like {weather.apparent_temperature_c:.0f}°C, "
            f"{WEATHER_CODE_MAP.get(weather.weather_code, 'current conditions unavailable')}, "
            f"humidity {weather.humidity_percent:.0f}%, wind {weather.wind_speed_kmh:.0f} km/h."
        )
        if weather.precipitation_mm > 0:
            summary += f" Precipitation: {weather.precipitation_mm:.1f} mm."

        observed_text = self._format_timestamp(weather.observed_at)
        fetched_text = self._format_timestamp(weather.fetched_at)
        source_text = weather.source or "weather provider"
        summary += f" Source: {source_text}."

        if cached:
            if fetched_text:
                summary += f" Last synced {fetched_text}."
            if observed_text:
                summary += f" Observed {observed_text}."
            summary += " Live weather is unavailable, so this may be stale."
        elif observed_text:
            summary += f" Observed {observed_text}."

        if location_is_approximate:
            summary += " Location is approximate because it comes from network geolocation rather than device GPS."
        return summary

    def _answer_location_query(self) -> Optional[str]:
        location = self.resolve_current_location()
        if location is None:
            return (
                "I don't have a reliable live location fix yet. "
                "Set IRIS_LOCATION_NAME or IRIS_LATITUDE and IRIS_LONGITUDE for an exact home location."
            )

        qualifier = "Approximate current location" if location.approximate else "Current location"
        message = (
            f"{qualifier}: {location.display_name} "
            f"({location.latitude:.4f}, {location.longitude:.4f}). "
            f"Timezone: {location.timezone}. Source: {location.source}."
        )
        if location.accuracy_m is not None:
            message += f" Accuracy is about {location.accuracy_m:.0f} meters."
        if location.approximate:
            message += " This is network-based, not device GPS."
        return message

    def resolve_current_location(self) -> Optional[LocationSnapshot]:
        configured = self._resolve_configured_location()
        if configured is not None:
            return configured

        cached = self._cache_get(self._location_cache, "current-location")
        if cached is not None:
            return cached

        for provider in self._current_location_providers():
            try:
                snapshot = provider()
            except Exception:
                snapshot = None
            if snapshot is None:
                continue
            self._remember_location("current-location", snapshot)
            self._cache_put(self._location_cache, "current-location", snapshot)
            return snapshot

        persisted = self._persistent_get_location("current-location")
        if persisted is not None:
            self._cache_put(self._location_cache, "current-location", persisted)
            return persisted
        return None

    def _resolve_configured_location(self) -> Optional[LocationSnapshot]:
        override_lat = getattr(Config, "LATITUDE_OVERRIDE", "").strip()
        override_lon = getattr(Config, "LONGITUDE_OVERRIDE", "").strip()
        override_name = getattr(Config, "LOCATION_NAME_OVERRIDE", "").strip()

        if override_lat and override_lon:
            try:
                latitude = float(override_lat)
                longitude = float(override_lon)
            except ValueError:
                latitude = longitude = None
            if latitude is not None and longitude is not None:
                return LocationSnapshot(
                    display_name=override_name or "Configured location",
                    city=override_name or "Configured location",
                    region="",
                    country="",
                    latitude=latitude,
                    longitude=longitude,
                    timezone="auto",
                    source="config override",
                    approximate=False,
                )

        if override_name:
            resolved = self.resolve_named_location(override_name)
            if resolved:
                resolved.source = "config override"
                resolved.approximate = False
                return resolved
        return None

    def _current_location_providers(self) -> list[Callable[[], Optional[LocationSnapshot]]]:
        return [
            self._resolve_windows_location,
            self._resolve_ipapi_location,
            self._resolve_ip_api_location,
        ]

    def _resolve_windows_location(self) -> Optional[LocationSnapshot]:
        if not sys.platform.startswith("win"):
            return None
        allow_local_geo, _ = self.resource_guard.allows_local_geo()
        if not allow_local_geo:
            return None

        payload = self._read_windows_location()
        if not payload:
            return None

        latitude = self._safe_float(payload.get("latitude"))
        longitude = self._safe_float(payload.get("longitude"))
        if latitude is None or longitude is None:
            return None

        location_name = {}
        if bool(getattr(Config, "ONLINE_LOCATION_NAME_ENRICHMENT", False)):
            location_name = self._reverse_geocode_coordinates(latitude, longitude)
        city = location_name.get("city", "")
        region = location_name.get("region", "")
        country = location_name.get("country", "")
        display_name = location_name.get("display_name") or "Current device location"
        accuracy = self._safe_float(payload.get("accuracy"))

        return LocationSnapshot(
            display_name=display_name,
            city=city or display_name,
            region=region,
            country=country,
            latitude=latitude,
            longitude=longitude,
            timezone=str(payload.get("timezone") or self._system_timezone_name() or "auto"),
            source="Windows location service",
            approximate=False,
            accuracy_m=accuracy,
        )

    def _resolve_ipapi_location(self) -> Optional[LocationSnapshot]:
        data = self._request_json("https://ipapi.co/json/", timeout=6)
        return self._build_location_snapshot(
            city=data.get("city"),
            region=data.get("region"),
            country=data.get("country_name"),
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            timezone=data.get("timezone"),
            source="ipapi.co",
            approximate=True,
        )

    def _resolve_ip_api_location(self) -> Optional[LocationSnapshot]:
        data = self._request_json(
            "http://ip-api.com/json/",
            params={
                "fields": "status,message,country,countryCode,region,regionName,city,lat,lon,timezone",
            },
            timeout=6,
        )
        if str(data.get("status") or "").lower() != "success":
            return None
        return self._build_location_snapshot(
            city=data.get("city"),
            region=data.get("regionName") or data.get("region"),
            country=data.get("country"),
            latitude=data.get("lat"),
            longitude=data.get("lon"),
            timezone=data.get("timezone"),
            source="ip-api.com",
            approximate=True,
        )

    def resolve_named_location(self, location_name: str) -> Optional[LocationSnapshot]:
        clean_name = self._normalize_location(location_name)
        if not clean_name:
            return None

        cache_key = f"geo:{clean_name.lower()}"
        cached = self._cache_get(self._location_cache, cache_key)
        if cached is not None:
            return cached

        persisted = self._persistent_get_location(cache_key)
        if persisted is not None:
            self._cache_put(self._location_cache, cache_key, persisted)
            return persisted

        try:
            payload = self._request_json(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": clean_name, "count": 1, "language": "en", "format": "json"},
                timeout=8,
            )
            results = payload.get("results") or []
            if not results:
                return None
            best = results[0]
            snapshot = self._build_location_snapshot(
                city=best.get("name") or clean_name,
                region=best.get("admin1"),
                country=best.get("country"),
                latitude=best.get("latitude"),
                longitude=best.get("longitude"),
                timezone=best.get("timezone"),
                source="Open-Meteo geocoding",
                approximate=False,
            )
            if snapshot is None:
                return None
            self._remember_location(cache_key, snapshot)
            self._cache_put(self._location_cache, cache_key, snapshot)
            return snapshot
        except Exception:
            return None

    def get_current_weather(self, location: LocationSnapshot) -> tuple[Optional[WeatherSnapshot], bool]:
        cache_key = f"weather:{location.latitude:.4f},{location.longitude:.4f}"
        cached = self._cache_get(self._weather_cache, cache_key)
        if cached is not None:
            if isinstance(cached, dict):
                snapshot = cached.get("snapshot")
                is_cached = bool(cached.get("cached"))
                if isinstance(snapshot, WeatherSnapshot):
                    return snapshot, is_cached
            if isinstance(cached, WeatherSnapshot):
                return cached, False

        try:
            payload = self._request_json(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                    "current": ",".join(
                        [
                            "temperature_2m",
                            "apparent_temperature",
                            "relative_humidity_2m",
                            "precipitation",
                            "weather_code",
                            "wind_speed_10m",
                            "wind_direction_10m",
                        ]
                    ),
                    "timezone": location.timezone or "auto",
                    "forecast_days": 1,
                },
                timeout=8,
            )
            current = payload.get("current") or {}
            snapshot = WeatherSnapshot(
                temperature_c=float(current["temperature_2m"]),
                apparent_temperature_c=float(current["apparent_temperature"]),
                humidity_percent=float(current["relative_humidity_2m"]),
                precipitation_mm=float(current["precipitation"]),
                wind_speed_kmh=float(current["wind_speed_10m"]),
                wind_direction_deg=float(current["wind_direction_10m"]),
                weather_code=int(current["weather_code"]),
                observed_at=str(current.get("time") or ""),
                source="Open-Meteo",
                fetched_at=datetime.now().astimezone().isoformat(),
            )
            self._remember_weather(cache_key, location, snapshot)
            self._cache_put(self._weather_cache, cache_key, {"snapshot": snapshot, "cached": False})
            return snapshot, False
        except Exception:
            persisted = self._persistent_get_weather(cache_key)
            if persisted is None:
                return None, False
            self._cache_put(self._weather_cache, cache_key, {"snapshot": persisted, "cached": True})
            return persisted, True

    def _extract_location_name(self, query: str) -> str:
        cleaned = (query or "").strip().rstrip("?.!")
        lowered = cleaned.lower()

        explicit_patterns = [
            r"\b(?:weather|forecast|temperature|humidity|wind|rain|snow)\s+(?:in|for|at)\s+(.+)$",
            r"\b(?:what's|what is|how's|how is)\s+the\s+(?:weather|temperature|forecast)\s+(?:in|for|at)\s+(.+)$",
            r"\b(?:in|for|at)\s+(.+)$",
        ]
        for pattern in explicit_patterns:
            match = re.search(pattern, lowered)
            if not match:
                continue
            return self._normalize_location(match.group(1))

        for keyword in ("weather", "forecast", "temperature"):
            prefix = f"{keyword} "
            if lowered.startswith(prefix):
                return self._normalize_location(cleaned[len(prefix):])

        return ""

    def _normalize_location(self, value: str) -> str:
        value = (value or "").strip().strip("?.!,")
        value = re.sub(r"\b(right now|now|currently|today|atm)\b", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+", " ", value).strip(" ,")
        return value

    def _resolve_cache_file(self, cache_file: Path | str | None) -> Path:
        if cache_file:
            candidate = Path(cache_file)
        else:
            candidate = Path(getattr(Config, "ENVIRONMENT_CACHE_FILE", "iris_environment_cache.json"))

        if not candidate.is_absolute():
            candidate = Path(__file__).resolve().parents[1] / candidate
        return candidate

    def _load_persistent_cache(self) -> dict[str, dict[str, Any]]:
        default_state = {"locations": {}, "weather": {}}
        try:
            if not self._persistent_cache_file.exists():
                return default_state
            payload = json.loads(self._persistent_cache_file.read_text(encoding="utf-8"))
        except Exception:
            return default_state

        if not isinstance(payload, dict):
            return default_state
        locations = payload.get("locations")
        weather = payload.get("weather")
        return {
            "locations": locations if isinstance(locations, dict) else {},
            "weather": weather if isinstance(weather, dict) else {},
        }

    def _save_persistent_cache(self) -> None:
        try:
            self._persistent_cache_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema": 1,
                "saved_at": datetime.now().astimezone().isoformat(),
                "locations": self._persistent_cache.get("locations", {}),
                "weather": self._persistent_cache.get("weather", {}),
            }
            self._persistent_cache_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _remember_location(self, key: str, snapshot: LocationSnapshot) -> None:
        self._persistent_cache.setdefault("locations", {})[key] = asdict(snapshot)
        self._save_persistent_cache()

    def _remember_weather(self, key: str, location: LocationSnapshot, snapshot: WeatherSnapshot) -> None:
        self._persistent_cache.setdefault("weather", {})[key] = {
            "location": asdict(location),
            "weather": asdict(snapshot),
        }
        self._save_persistent_cache()

    def _persistent_get_location(self, key: str) -> Optional[LocationSnapshot]:
        payload = self._persistent_cache.get("locations", {}).get(key)
        if not isinstance(payload, dict):
            return None
        try:
            return LocationSnapshot(**payload)
        except TypeError:
            return None

    def _persistent_get_weather(self, key: str) -> Optional[WeatherSnapshot]:
        payload = self._persistent_cache.get("weather", {}).get(key)
        if not isinstance(payload, dict):
            return None
        weather_payload = payload.get("weather")
        if not isinstance(weather_payload, dict):
            return None
        try:
            return WeatherSnapshot(**weather_payload)
        except TypeError:
            return None

    def _format_timestamp(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return text

        if dt.tzinfo is None:
            return dt.strftime("%H:%M local time on %B %d")
        return dt.astimezone().strftime("%H:%M local time on %B %d")

    def _request_json(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        timeout: int = 8,
    ) -> dict[str, Any]:
        response = requests.get(
            url,
            params=params,
            timeout=timeout,
            headers=self._http_headers,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object response.")
        return payload

    def _build_location_snapshot(
        self,
        city: Any,
        region: Any,
        country: Any,
        latitude: Any,
        longitude: Any,
        timezone: Any,
        source: str,
        approximate: bool,
    ) -> Optional[LocationSnapshot]:
        latitude_value = self._safe_float(latitude)
        longitude_value = self._safe_float(longitude)
        if latitude_value is None or longitude_value is None:
            return None

        city_text = str(city or "").strip()
        region_text = str(region or "").strip()
        country_text = str(country or "").strip()
        display_name = self._build_display_name(city_text, region_text, country_text)

        return LocationSnapshot(
            display_name=display_name,
            city=city_text or display_name,
            region=region_text,
            country=country_text,
            latitude=latitude_value,
            longitude=longitude_value,
            timezone=str(timezone or "auto").strip() or "auto",
            source=source,
            approximate=approximate,
        )

    def _build_display_name(self, city: str, region: str, country: str) -> str:
        display_bits = [bit for bit in [city, region, country] if bit]
        return ", ".join(display_bits) if display_bits else "Approximate network location"

    def _reverse_geocode_coordinates(self, latitude: float, longitude: float) -> dict[str, str]:
        try:
            payload = self._request_json(
                "https://nominatim.openstreetmap.org/reverse",
                params={
                    "lat": latitude,
                    "lon": longitude,
                    "format": "jsonv2",
                    "zoom": 10,
                    "accept-language": "en",
                },
                timeout=8,
            )
        except Exception:
            return {}

        address = payload.get("address") or {}
        city = self._first_non_empty(
            [
                address.get("city"),
                address.get("town"),
                address.get("village"),
                payload.get("name"),
            ]
        )
        region = self._first_non_empty(
            [
                address.get("state"),
                address.get("county"),
                address.get("region"),
            ]
        )
        country = self._first_non_empty([address.get("country")])
        display_name = str(payload.get("display_name") or "").strip()
        if not display_name:
            display_name = self._build_display_name(city, region, country)

        return {
            "city": city,
            "region": region,
            "country": country,
            "display_name": display_name,
        }

    def _read_windows_location(self) -> Optional[dict[str, Any]]:
        script = """
[Windows.Devices.Geolocation.Geolocator, Windows.Devices.Geolocation, ContentType = WindowsRuntime] | Out-Null
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$geo = New-Object Windows.Devices.Geolocation.Geolocator
$op = $geo.GetGeopositionAsync()
$method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 } | Select-Object -First 1
$generic = $method.MakeGenericMethod([Windows.Devices.Geolocation.Geoposition])
$task = $generic.Invoke($null, @($op))
$pos = $task.GetAwaiter().GetResult()
$coord = $pos.Coordinate.Point.Position
[PSCustomObject]@{
  latitude = $coord.Latitude
  longitude = $coord.Longitude
  accuracy = $pos.Coordinate.Accuracy
  timestamp = $pos.Coordinate.Timestamp.ToString("o")
  timezone = (Get-TimeZone).Id
} | ConvertTo-Json -Compress
""".strip()

        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
        except Exception:
            return None

        if completed.returncode != 0:
            return None

        output = (completed.stdout or "").strip()
        if not output:
            return None

        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _system_timezone_name(self) -> str:
        now = datetime.now().astimezone()
        return now.tzname() or "local time"

    def _first_non_empty(self, values: list[Any]) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    def _safe_float(self, value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _cache_get(self, bucket: dict, key: str):
        cached = bucket.get(key)
        if not cached:
            return None
        stored_at, value = cached
        if time.time() - stored_at > self._cache_ttl_seconds:
            bucket.pop(key, None)
            return None
        return value

    def _cache_put(self, bucket: dict, key: str, value) -> None:
        bucket[key] = (time.time(), value)
