from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_researcher_returns_fallback_string_when_synthesis_is_empty():
    import tools.researcher as researcher_module

    brain = MagicMock()
    brain._call_api.return_value = None
    researcher = researcher_module.Researcher(brain)
    fake_ddgs = MagicMock()
    fake_ddgs.__enter__.return_value.text.return_value = iter(
        [
            {"title": "Result One", "body": "Useful current information."},
            {"title": "Result Two", "body": "A second useful snippet."},
        ]
    )

    with patch.object(researcher_module, "DDGS", return_value=fake_ddgs):
        response = researcher.search("search for iris reliability")

    assert isinstance(response, str)
    assert response
    assert "Result One" in response
    brain._call_api.assert_called_once()


def test_researcher_empty_query_never_calls_search_provider():
    import tools.researcher as researcher_module

    brain = MagicMock()
    researcher = researcher_module.Researcher(brain)

    with patch.object(researcher_module, "DDGS") as ddgs:
        response = researcher.search("search for")

    assert "what you want me to search" in response.lower()
    ddgs.assert_not_called()


def test_generic_weather_query_uses_personal_default_location():
    from core.weather import extract_location

    with patch.dict("os.environ", {"IRIS_DEFAULT_LOCATION": "Berlin,DE"}):
        assert extract_location("what's the weather outside?") == "Berlin,DE"


def test_explicit_weather_location_wins_over_default():
    from core.weather import extract_location

    with patch.dict("os.environ", {"IRIS_DEFAULT_LOCATION": "Berlin,DE"}):
        assert extract_location("what is the weather in Hamburg today?") == "Hamburg"


def test_forecast_labels_use_destination_timezone_offset():
    from core.weather import _local_forecast_label

    # 2024-01-01 00:00 UTC + India Standard Time offset = 05:30.
    assert _local_forecast_label(1704067200, 19800) == "Mon 05:30"


def test_malformed_current_weather_payload_fails_without_guessing():
    import core.weather as weather_module

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"cod": 200, "main": {}}

    with patch.object(weather_module.Config, "OPENWEATHER_API_KEY", "test-key"), patch.object(
        weather_module,
        "_geocode",
        return_value=(52.52, 13.405, "Berlin", "DE"),
    ), patch.object(weather_module.requests, "get", return_value=response):
        result = weather_module.get_current_weather("Berlin")

    assert "incomplete" in result.lower()
    assert "won't guess" in result.lower()
