from fastapi import FastAPI, Form
from starlette.requests import Request
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from geonamescache import GeonamesCache
import openmeteo_requests
from geopy.geocoders import Nominatim
import requests_cache
import pandas as pd
from retry_requests import retry
from typing import Tuple, Optional

app = FastAPI()

# Настройка шаблонов и статических файлов
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Инициализация кэша городов
gc = GeonamesCache()
eng_cities = [city['name'] for city in gc.get_cities().values()]


def get_coordinates(city_name: str) -> Optional[Tuple[float, float]]:
    """Получение координат города."""
    geolocator = Nominatim(user_agent="my_weather_app")
    location = geolocator.geocode(city_name)
    if location:
        return location.latitude, location.longitude
    print(f"Не удалось найти координаты для города {city_name}")
    return None


def get_weather(city_name: str) -> Optional[Tuple[str, str]]:
    """Получение прогноза погоды для города."""
    coordinates = get_coordinates(city_name)
    if not coordinates:
        return None

    latitude, longitude = coordinates

    # Настройка клиента API Open-Meteo
    cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
    retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
    openmeteo = openmeteo_requests.Client(session=retry_session)

    # Параметры запроса
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "temperature_2m",
        "forecast_days": 1
    }

    response = openmeteo.weather_api(url, params=params)[0]

    # Формирование данных о погоде
    data = (f"Погода для города {city_name}\n"
            f"Координаты {response.Latitude()}°N {response.Longitude()}°E\n"
            f"Высота над уровнем моря {response.Elevation()} м\n")

    # Обработка почасовых данных
    hourly = response.Hourly()
    hourly_data = {
        "date": pd.date_range(
            start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=hourly.Interval()),
            inclusive="left"
        ),
        "temperature_2m": hourly.Variables(0).ValuesAsNumpy()
    }

    hourly_dataframe = pd.DataFrame(data=hourly_data)
    return hourly_dataframe.to_html(), data


@app.get("/")
async def home(request: Request):
    """Отображение домашней страницы."""
    return templates.TemplateResponse("index.html", {"request": request, "cities": eng_cities})


@app.post("/")
async def select_city(request: Request, city: str = Form(...)):
    """Обработка выбора города и отображение прогноза погоды."""
    weather_data = get_weather(city)
    if weather_data:
        result, data = weather_data
        return templates.TemplateResponse("index.html", {
            "request": request,
            "cities": eng_cities,
            "result": result,
            "data": data
        })
    else:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "cities": eng_cities,
            "error": f"Не удалось получить данные о погоде для города {city}"
        })