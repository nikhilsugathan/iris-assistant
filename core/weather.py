"""IRIS weather integration using OpenWeatherMap."""

from __future__ import annotations

import datetime
import os
import re

import requests

from config import Config
from core import logger as _logger_mod


logger = _logger_mod.get_logger("Weather")

WEATHER_KEYWORDS = (
    "weather",
    "forecast",
    "temperature",
    "degrees",
    "rain",
    "sunny",
    "cloudy",
    "snow",
    "wind",
    "humidity",
    "hot outside",
    "cold outside",
    "how hot",
    "how cold",
    "what's it like outside",
    "what is it like outside",
)

_GEOCODE_URL = "https://api.openweathermap.org/geo/1.0/direct"
_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

_INDIA_STATE_TO_CITY: dict[str, str] = {
    "andhra pradesh": "Visakhapatnam,IN",
    "arunachal pradesh": "Itanagar,IN",
    "assam": "Guwahati,IN",
    "bihar": "Patna,IN",
    "chhattisgarh": "Raipur,IN",
    "goa": "Panaji,IN",
    "gujarat": "Ahmedabad,IN",
    "haryana": "Chandigarh,IN",
    "himachal pradesh": "Shimla,IN",
    "jharkhand": "Ranchi,IN",
    "karnataka": "Bengaluru,IN",
    "kerala": "Thiruvananthapuram,IN",
    "madhya pradesh": "Bhopal,IN",
    "maharashtra": "Mumbai,IN",
    "manipur": "Imphal,IN",
    "meghalaya": "Shillong,IN",
    "mizoram": "Aizawl,IN",
    "nagaland": "Kohima,IN",
    "odisha": "Bhubaneswar,IN",
    "punjab": "Chandigarh,IN",
    "rajasthan": "Jaipur,IN",
    "sikkim": "Gangtok,IN",
    "tamil nadu": "Chennai,IN",
    "telangana": "Hyderabad,IN",
    "tripura": "Agartala,IN",
    "uttar pradesh": "Lucknow,IN",
    "uttarakhand": "Dehradun,IN",
    "west bengal": "Kolkata,IN",
    "delhi": "New Delhi,IN",
    "mumbai": "Mumbai,IN",
    "bangalore": "Bengaluru,IN",
    "bengaluru": "Bengaluru,IN",
    "bombay": "Mumbai,IN",
    "calcutta": "Kolkata,IN",
    "madras": "Chennai,IN",
    "trivandrum": "Thiruvananthapuram,IN",
    "kochi": "Kochi,IN",
    "cochin": "Kochi,IN",
    "hyderabad": "Hyderabad,IN",
    "chennai": "Chennai,IN",
    "kolkata": "Kolkata,IN",
}

_CITY_RE = re.compile(
    r"(?:weather|forecast|temperature|degrees|climate)"
    r".*?(?:in|for|at|of)\s+([A-Za-z][a-zA-Z\s\-]{2,30}?)(?:\?|$|[,.]|\s+(?:now|today|tonight|tomorrow))",
    re.IGNORECASE,
)
_CITY_RE2 = re.compile(
    r"(?:in|for|at)\s+([A-Za-z][a-zA-Z\s\-]{2,30})(?:\?|$|[,.]|\s+(?:weather|forecast|temperature|now|today))",
    re.IGNORECASE,
)


def is_weather_query(text: str) -> bool:
    value = str(text or "").lower()
    return any(keyword in value for keyword in WEATHER_KEYWORDS)


def extract_location(text: str) -> str | None:
    """Extract an explicit location or use the configured personal default."""
    value = str(text or "")
    for pattern in (_CITY_RE, _CITY_RE2):
        match = pattern.search(value)
        if match:
            location = match.group(1).strip().rstrip("?.,")
            if len(location) >= 3:
                return location

    fallback = re.search(r"([A-Za-z][a-zA-Z\s]{2,25}?)\s+weather", value, re.IGNORECASE)
    if fallback:
        candidate = fallback.group(1).strip()
        generic_prefixes = {"the", "today", "current", "outside", "what is the", "what s the"}
        if candidate.lower() not in generic_prefixes:
            return candidate

    if is_weather_query(value):
        default_location = os.getenv("IRIS_DEFAULT_LOCATION", "Berlin,DE").strip()
        return default_location or None
    return None


def _resolve_location(city: str) -> str:
    key = city.strip().lower()
    resolved = _INDIA_STATE_TO_CITY.get(key)
    if resolved:
        logger.debug("[Weather] Resolved %r to %r", city, resolved)
        return resolved
    return city


def _geocode(city: str) -> tuple[float, float, str, str] | None:
    api_key = getattr(Config, "OPENWEATHER_API_KEY", "")
    if not api_key:
        return None

    city = _resolve_location(city)
    target_country: str | None = None
    if "," in city:
        parts = city.split(",")
        country_code = parts[-1].strip().upper()
        if len(country_code) == 2 and country_code.isalpha():
            target_country = country_code

    try:
        response = requests.get(
            _GEOCODE_URL,
            params={"q": city, "limit": 5, "appid": api_key},
            timeout=6,
        )
        response.raise_for_status()
        data = response.json()
        if not data or not isinstance(data, list):
            return None

        candidates = data
        if target_country:
            preferred = [
                result
                for result in candidates
                if str(result.get("country", "")).upper() == target_country
            ]
            if preferred:
                candidates = preferred

        result = candidates[0]
        display = result.get("local_names", {}).get("en") or result["name"]
        return float(result["lat"]), float(result["lon"]), str(display), str(result.get("country", ""))
    except Exception as exc:
        logger.debug("[Weather] Geocode error for %r: %s", city, exc)
        return None


def get_current_weather(location: str, units: str = "metric") -> str:
    api_key = getattr(Config, "OPENWEATHER_API_KEY", "")
    if not api_key:
        return "I'd love to check the weather, but I don't have an API key set up."

    geo = _geocode(location)
    if not geo:
        return f"Couldn't find a place called '{location}' — double-check the spelling?"

    lat, lon, city_name, country = geo
    try:
        response = requests.get(
            _WEATHER_URL,
            params={"lat": lat, "lon": lon, "appid": api_key, "units": units},
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.warning("[Weather] API error: %s", exc)
        return "Weather lookup hit a snag — try again in a moment."

    if data.get("cod") != 200:
        return f"Weather data unavailable: {data.get('message', 'unknown error')}."

    try:
        unit_symbol = "°C" if units == "metric" else "°F"
        speed_unit = "m/s" if units == "metric" else "mph"
        description = data["weather"][0]["description"].capitalize() if data.get("weather") else "Unknown"
        temperature = round(data["main"]["temp"])
        feels_like = round(data["main"]["feels_like"])
        humidity = data["main"]["humidity"]
        wind = round(data.get("wind", {}).get("speed", 0))
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("[Weather] Malformed current weather response: %s", exc)
        return "Weather data came back incomplete, so I won't guess the conditions."

    location_string = f"{city_name}, {country}" if country else city_name
    return (
        f"{location_string}: {description}. "
        f"{temperature}{unit_symbol}, feels like {feels_like}{unit_symbol}. "
        f"Humidity {humidity}%, wind {wind} {speed_unit}."
    )


def _local_forecast_label(unix_seconds: int, timezone_offset_seconds: int) -> str:
    utc_time = datetime.datetime.fromtimestamp(unix_seconds, tz=datetime.timezone.utc)
    local_time = utc_time + datetime.timedelta(seconds=timezone_offset_seconds)
    return local_time.strftime("%a %H:%M")


def get_forecast(location: str, units: str = "metric") -> str:
    api_key = getattr(Config, "OPENWEATHER_API_KEY", "")
    if not api_key:
        return "I'd love to give you a forecast, but I don't have an API key set up."

    geo = _geocode(location)
    if not geo:
        return f"Couldn't find a place called '{location}'."

    lat, lon, city_name, country = geo
    try:
        response = requests.get(
            _FORECAST_URL,
            params={"lat": lat, "lon": lon, "appid": api_key, "units": units, "cnt": 8},
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.warning("[Weather] Forecast error: %s", exc)
        return "Forecast lookup hit a snag."

    if str(data.get("cod")) != "200":
        return f"Forecast unavailable: {data.get('message', 'unknown error')}."

    unit_symbol = "°C" if units == "metric" else "°F"
    location_string = f"{city_name}, {country}" if country else city_name
    periods = data.get("list", [])[:4]
    if not periods:
        return f"No forecast data available for {location_string}."

    try:
        timezone_offset = int(data.get("city", {}).get("timezone", 0))
        parts = []
        for period in periods:
            label = _local_forecast_label(int(period["dt"]), timezone_offset)
            temperature = round(period["main"]["temp"])
            description = period["weather"][0]["description"] if period.get("weather") else "unknown conditions"
            parts.append(f"{label}: {description}, {temperature}{unit_symbol}")
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("[Weather] Malformed forecast response: %s", exc)
        return "Forecast data came back incomplete, so I won't invent missing periods."

    return f"{location_string} forecast — " + " | ".join(parts) + "."
