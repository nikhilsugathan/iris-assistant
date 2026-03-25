"""
IRIS live-data routing smoke test.

Verifies that weather and location queries use the deterministic environment
path instead of the generic model path.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from core.engine import IRISEngine
from core.environment import EnvironmentIntel, LocationSnapshot, WeatherSnapshot


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeEnvironment:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def answer_query(self, query: str):
        self.queries.append(query)
        lowered = query.lower()
        if "berlin" in lowered and "weather" in lowered:
            return "Berlin, Germany right now: 10°C, feels like 8°C, overcast, humidity 81%, wind 14 km/h."
        if "where am i" in lowered:
            return "Current location: Berlin, Germany (52.5200, 13.4050). Timezone: Europe/Berlin. Source: Windows location service. Accuracy is about 120 meters."
        if "what time is it" in lowered:
            return "It's 12:52 on Wednesday, March 25, 2026 in W. Europe Standard Time."
        return None


class FallbackEnvironmentIntel(EnvironmentIntel):
    def __init__(self) -> None:
        super().__init__()
        self.provider_calls: list[str] = []

    def _current_location_providers(self):
        return [self._fail_provider, self._success_provider]

    def _fail_provider(self):
        self.provider_calls.append("fail")
        return None

    def _success_provider(self):
        self.provider_calls.append("success")
        return LocationSnapshot(
            display_name="Berlin, Germany",
            city="Berlin",
            region="Berlin",
            country="Germany",
            latitude=52.5200,
            longitude=13.4050,
            timezone="Europe/Berlin",
            source="fallback-provider",
            approximate=False,
            accuracy_m=45.0,
        )


class OfflineWeatherEnvironmentIntel(EnvironmentIntel):
    def _request_json(self, url: str, params=None, timeout: int = 8):
        if "api.open-meteo.com" in url:
            raise RuntimeError("offline")
        return super()._request_json(url, params=params, timeout=timeout)


def main() -> None:
    engine = IRISEngine(text_mode=True)
    fake_environment = FakeEnvironment()
    engine.brain.environment = fake_environment

    try:
        weather_result = engine.process_user_input("what's the weather in Berlin right now", speak_response=False)
        assert_true(
            "Berlin, Germany right now: 10°C" in weather_result.response,
            "Weather query did not route through the live-data handler.",
        )

        location_result = engine.process_user_input("where am i", speak_response=False)
        assert_true(
            "Current location: Berlin" in location_result.response,
            "Location query did not route through the live-data handler.",
        )

        time_result = engine.process_user_input("what time is it", speak_response=False)
        assert_true(
            "W. Europe Standard Time" in time_result.response,
            "Time query did not route through the live-data handler.",
        )

        assert_true(len(fake_environment.queries) >= 3, "Live-data handler was not consulted for all live-data queries.")

        fallback_intel = FallbackEnvironmentIntel()
        resolved = fallback_intel.resolve_current_location()
        assert_true(resolved is not None, "Fallback provider chain did not resolve a current location.")
        assert_true(
            resolved.source == "fallback-provider",
            "Fallback provider chain did not return the successful provider result.",
        )
        assert_true(
            fallback_intel.provider_calls == ["fail", "success"],
            "Fallback providers were not consulted in the expected order.",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "env-cache.json"
            seed_intel = EnvironmentIntel(cache_file=cache_path)
            berlin = LocationSnapshot(
                display_name="Berlin, Germany",
                city="Berlin",
                region="Berlin",
                country="Germany",
                latitude=52.5200,
                longitude=13.4050,
                timezone="Europe/Berlin",
                source="Open-Meteo geocoding",
                approximate=False,
            )
            seed_intel._remember_location("geo:berlin", berlin)
            seed_intel._remember_weather(
                "weather:52.5200,13.4050",
                berlin,
                WeatherSnapshot(
                    temperature_c=10.0,
                    apparent_temperature_c=8.0,
                    humidity_percent=81.0,
                    precipitation_mm=0.0,
                    wind_speed_kmh=14.0,
                    wind_direction_deg=220.0,
                    weather_code=3,
                    observed_at="2026-03-25T10:00",
                    source="Open-Meteo",
                    fetched_at="2026-03-25T10:05:00+01:00",
                ),
            )

            offline_intel = OfflineWeatherEnvironmentIntel(cache_file=cache_path)
            offline_weather = offline_intel.answer_query("what's the weather in Berlin right now")
            assert_true(
                offline_weather is not None and "Last synced weather for Berlin, Germany" in offline_weather,
                "Offline weather fallback did not use the persisted last-known weather snapshot.",
            )
            assert_true(
                "Source: Open-Meteo." in offline_weather and "Last synced" in offline_weather,
                "Offline weather fallback should include source and sync timing.",
            )

        print("PASS: IRIS live-data smoke test completed.")
    finally:
        engine.shutdown()


if __name__ == "__main__":
    main()
