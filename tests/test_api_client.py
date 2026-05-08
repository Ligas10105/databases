"""Tests for collector.api_client — OWM parser and Open-Meteo fallback."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector import api_client


CITY = {"name": "Warsaw", "country": "PL", "lat": 52.23, "lon": 21.01}


def _mock_response(status: int = 200, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data or {}
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    else:
        resp.raise_for_status.return_value = None
    return resp


OWM_PAYLOAD = {
    "dt": 1_700_000_000,
    "main": {
        "temp": 5.2,
        "feels_like": 2.1,
        "temp_min": 3.0,
        "temp_max": 7.5,
        "humidity": 78,
        "pressure": 1013,
    },
    "wind": {"speed": 4.5, "deg": 270},
    "clouds": {"all": 40},
    "weather": [{"main": "Clouds", "description": "scattered clouds"}],
}


def test_fetch_owm_success():
    with patch("collector.api_client.requests.get",
               return_value=_mock_response(200, OWM_PAYLOAD)) as mock_get:
        out = api_client.fetch_owm(CITY, "fake_key")

    assert out is not None
    assert out["temp_c"] == 5.2
    assert out["humidity_pct"] == 78
    assert out["pressure_hpa"] == 1013
    assert out["wind_speed_ms"] == 4.5
    assert out["wind_deg"] == 270
    assert out["clouds_pct"] == 40
    assert out["weather_main"] == "Clouds"
    assert out["weather_desc"] == "scattered clouds"
    assert out["source"] == "owm"
    assert out["timestamp"].endswith("Z")

    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert kwargs["params"]["q"] == "Warsaw,PL"
    assert kwargs["params"]["appid"] == "fake_key"
    assert kwargs["params"]["units"] == "metric"


@pytest.mark.parametrize("status", [401, 429, 500])
def test_fetch_owm_returns_none_on_http_error(status):
    with patch("collector.api_client.requests.get",
               return_value=_mock_response(status)):
        out = api_client.fetch_owm(CITY, "fake_key")
    assert out is None


def test_fetch_owm_returns_none_on_network_error():
    with patch("collector.api_client.requests.get",
               side_effect=requests.ConnectionError("boom")):
        out = api_client.fetch_owm(CITY, "fake_key")
    assert out is None


def test_fetch_owm_handles_missing_fields():
    with patch("collector.api_client.requests.get",
               return_value=_mock_response(200, {"main": {}, "weather": []})):
        out = api_client.fetch_owm(CITY, "fake_key")
    assert out is not None
    assert out["temp_c"] is None
    assert out["weather_main"] is None


OPEN_METEO_PAYLOAD = {
    "current_weather": {
        "temperature": 4.8,
        "windspeed": 14.4,
        "winddirection": 200,
        "weathercode": 3,
        "time": "2024-01-15T12:00",
    },
    "hourly": {
        "time": ["2024-01-15T11:00", "2024-01-15T12:00", "2024-01-15T13:00"],
        "temperature_2m": [4.0, 4.8, 5.1],
        "relativehumidity_2m": [80, 76, 70],
        "pressure_msl": [1010, 1011, 1012],
        "windspeed_10m": [13.0, 14.4, 15.0],
        "cloudcover": [60, 90, 95],
    },
}


def test_fetch_open_meteo_success():
    with patch("collector.api_client.requests.get",
               return_value=_mock_response(200, OPEN_METEO_PAYLOAD)):
        out = api_client.fetch_open_meteo(CITY)

    assert out is not None
    assert out["temp_c"] == 4.8
    assert out["humidity_pct"] == 76
    assert out["pressure_hpa"] == 1011
    assert out["wind_speed_ms"] == round(14.4 / 3.6, 2)
    assert out["wind_deg"] == 200
    assert out["clouds_pct"] == 90
    assert out["weather_main"] == "Clouds"
    assert out["source"] == "open_meteo"


def test_fetch_open_meteo_returns_none_on_error():
    with patch("collector.api_client.requests.get",
               side_effect=requests.Timeout("slow")):
        assert api_client.fetch_open_meteo(CITY) is None


def test_fallback_logic_when_owm_fails():
    """When OWM returns 401, the fallback to Open-Meteo should yield a record."""
    call_count = {"n": 0}

    def fake_get(url, *args, **kwargs):
        call_count["n"] += 1
        if "openweathermap" in url:
            return _mock_response(401)
        return _mock_response(200, OPEN_METEO_PAYLOAD)

    with patch("collector.api_client.requests.get", side_effect=fake_get):
        owm = api_client.fetch_owm(CITY, "bad_key")
        assert owm is None
        meteo = api_client.fetch_open_meteo(CITY)
        assert meteo is not None
        assert meteo["source"] == "open_meteo"

    assert call_count["n"] == 2
