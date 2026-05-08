"""HTTP clients for OpenWeatherMap (primary) and Open-Meteo (fallback)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OWM_URL = "https://api.openweathermap.org/data/2.5/weather"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_TIMEOUT = 10


def _utc_iso(ts: int | None = None) -> str:
    """Return UTC ISO 8601 timestamp (without microseconds, with 'Z')."""
    if ts is None:
        dt = datetime.now(timezone.utc)
    else:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_owm(city: dict, api_key: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[dict]:
    """Fetch current weather from OpenWeatherMap. Returns normalized dict or None."""
    params = {
        "q": f"{city['name']},{city['country']}",
        "appid": api_key,
        "units": "metric",
    }
    try:
        resp = requests.get(OWM_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        logger.warning("OWM request failed for %s: %s", city.get("name"), exc)
        return None
    except ValueError as exc:
        logger.warning("OWM returned non-JSON for %s: %s", city.get("name"), exc)
        return None

    try:
        main = payload.get("main", {}) or {}
        wind = payload.get("wind", {}) or {}
        clouds = payload.get("clouds", {}) or {}
        weather_list = payload.get("weather") or [{}]
        weather = weather_list[0] if weather_list else {}

        return {
            "timestamp": _utc_iso(payload.get("dt")),
            "temp_c": main.get("temp"),
            "feels_like_c": main.get("feels_like"),
            "temp_min_c": main.get("temp_min"),
            "temp_max_c": main.get("temp_max"),
            "humidity_pct": main.get("humidity"),
            "pressure_hpa": main.get("pressure"),
            "wind_speed_ms": wind.get("speed"),
            "wind_deg": wind.get("deg"),
            "clouds_pct": clouds.get("all"),
            "weather_main": weather.get("main"),
            "weather_desc": weather.get("description"),
            "source": "owm",
        }
    except (KeyError, TypeError) as exc:
        logger.warning("OWM parse error for %s: %s", city.get("name"), exc)
        return None


def fetch_open_meteo(city: dict, timeout: int = DEFAULT_TIMEOUT) -> Optional[dict]:
    """Fetch current weather from Open-Meteo (fallback). Returns normalized dict or None."""
    params = {
        "latitude": city["lat"],
        "longitude": city["lon"],
        "current_weather": "true",
        "hourly": "temperature_2m,relativehumidity_2m,pressure_msl,windspeed_10m,cloudcover",
    }
    try:
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        logger.warning("Open-Meteo request failed for %s: %s", city.get("name"), exc)
        return None
    except ValueError as exc:
        logger.warning("Open-Meteo returned non-JSON for %s: %s", city.get("name"), exc)
        return None

    try:
        current = payload.get("current_weather") or {}
        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []

        cur_time = current.get("time")
        idx = times.index(cur_time) if cur_time and cur_time in times else -1

        def _at(key: str):
            arr = hourly.get(key) or []
            if not arr:
                return None
            try:
                return arr[idx]
            except IndexError:
                return arr[-1]

        humidity = _at("relativehumidity_2m")
        pressure = _at("pressure_msl")
        clouds = _at("cloudcover")

        return {
            "timestamp": _utc_iso(),
            "temp_c": current.get("temperature"),
            "feels_like_c": None,
            "temp_min_c": None,
            "temp_max_c": None,
            "humidity_pct": int(humidity) if humidity is not None else None,
            "pressure_hpa": int(pressure) if pressure is not None else None,
            "wind_speed_ms": _kmh_to_ms(current.get("windspeed")),
            "wind_deg": current.get("winddirection"),
            "clouds_pct": int(clouds) if clouds is not None else None,
            "weather_main": _wmo_to_main(current.get("weathercode")),
            "weather_desc": _wmo_to_desc(current.get("weathercode")),
            "source": "open_meteo",
        }
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Open-Meteo parse error for %s: %s", city.get("name"), exc)
        return None


def _kmh_to_ms(kmh: float | None) -> float | None:
    if kmh is None:
        return None
    return round(kmh / 3.6, 2)


_WMO_MAIN = {
    0: "Clear",
    1: "Clear", 2: "Clouds", 3: "Clouds",
    45: "Fog", 48: "Fog",
    51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
    56: "Drizzle", 57: "Drizzle",
    61: "Rain", 63: "Rain", 65: "Rain",
    66: "Rain", 67: "Rain",
    71: "Snow", 73: "Snow", 75: "Snow", 77: "Snow",
    80: "Rain", 81: "Rain", 82: "Rain",
    85: "Snow", 86: "Snow",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}

_WMO_DESC = {
    0: "clear sky",
    1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "slight snow", 73: "moderate snow", 75: "heavy snow", 77: "snow grains",
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}


def _wmo_to_main(code: int | None) -> str | None:
    if code is None:
        return None
    return _WMO_MAIN.get(int(code), "Unknown")


def _wmo_to_desc(code: int | None) -> str | None:
    if code is None:
        return None
    return _WMO_DESC.get(int(code), "unknown")
