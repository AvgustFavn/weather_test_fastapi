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
import sqlite3

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
geonames_cache = GeonamesCache()
english_cities = [city['name'] for city in geonames_cache.get_cities().values()]

def get_city_coordinates(city_name: str) -> Optional[Tuple[float, float]]:
    geolocator = Nominatim(user_agent="my_weather_app")
    location = geolocator.geocode(city_name)
    return (location.latitude, location.longitude) if location else None

def get_weather_data(city_name: str) -> Optional[Tuple[str, str]]:
    coordinates = get_city_coordinates(city_name)
    if not coordinates:
        return None

    latitude, longitude = coordinates
    cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
    retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
    openmeteo_client = openmeteo_requests.Client(session=retry_session)

    response = openmeteo_client.weather_api(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m",
            "forecast_days": 1
        }
    )[0]

    data = (
        f"Погода для города {city_name}\n"
        f"Координаты {response.Latitude()}°N {response.Longitude()}°E\n"
        f"Высота над уровнем моря {response.Elevation()} м\n"
    )

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

def init_db():
    conn = sqlite3.connect("weather.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            last_city TEXT,
            search_history TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_user_data(user_id: int, last_city: str, search_history: str):
    conn = sqlite3.connect("weather.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (id, last_city, search_history)
        VALUES (?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            last_city = excluded.last_city,
            search_history = excluded.search_history
    """, (user_id, last_city, search_history))
    conn.commit()
    conn.close()

def get_user_data(user_id: int) -> Optional[Tuple[str, str]]:
    conn = sqlite3.connect("weather.db")
    cursor = conn.cursor()
    cursor.execute("SELECT last_city, search_history FROM users WHERE id=?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result

@app.get("/")
async def home(request: Request):
    user_id = str(request.client.host).replace('.', '')
    last_city, search_history = get_user_data(user_id) or ("", "")
    weather_data = get_weather_data(last_city) if last_city else None

    context = {
        "request": request,
        "cities": english_cities,
        "last_city": last_city,
        "search_history": search_history,
    }

    if weather_data:
        result, data = weather_data
        context.update({"result": result, "data": data})

    return templates.TemplateResponse("index.html", context)

@app.get("/api/search_history/{city}")
async def search_history(city: str):
    conn = sqlite3.connect("weather.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE search_history LIKE '%," + city + ",%'")
    result = cursor.fetchone()[0]
    if result > 0:
        result += 1
    conn.close()
    return {"city": city, "count": result}

@app.post("/")
async def select_city(request: Request, city: str = Form(...)):
    weather_data = get_weather_data(city)

    if weather_data:
        result, data = weather_data
        user_id = str(request.client.host).replace('.', '')

        try:
            search_history = get_user_data(user_id)[1]
            search_history = search_history.strip(",") + "," + city
        except:
            search_history = city

        save_user_data(int(user_id), city, search_history)
        last_city, search_history = get_user_data(user_id) or ("", "")
        last_city = city

        response = templates.TemplateResponse("index.html", {
            "request": request,
            "cities": english_cities,
            "result": result,
            "data": data,
            "last_city": last_city,
            "search_history": search_history
        })
        response.set_cookie(key="last_city", value=city)
        return response
    else:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "cities": english_cities,
            "error": f"Не удалось получить данные о погоде для города {city}"
        })

init_db()