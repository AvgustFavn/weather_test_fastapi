import pytest
import requests
import os
from main import get_city_coordinates, get_weather_data, init_db, save_user_data, get_user_data

BASE_URL = "http://localhost:8000"

def test_home():
    response = requests.get(f"{BASE_URL}/")
    assert response.status_code == 200

def test_get_city_coordinates():
    coordinates = get_city_coordinates("London")
    assert coordinates is not None
    assert len(coordinates) == 2
    assert isinstance(coordinates[0], float)
    assert isinstance(coordinates[1], float)

def test_get_weather_data():
    weather_data = get_weather_data("London")
    assert weather_data is not None
    assert len(weather_data) == 2
    assert isinstance(weather_data[0], str)
    assert isinstance(weather_data[1], str)

def test_save_and_get_user_data(tmpdir):
    import sqlite3
    db_path = tmpdir.join("test.db")
    os.environ["DATABASE_PATH"] = str(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        init_db()
        save_user_data(1, "London", "London,Paris")
        result = get_user_data(1)
        assert result == ("London", "London,Paris")

def test_select_city():
    response = requests.post(f"{BASE_URL}/", data={"city": "London"})
    assert response.status_code == 200
    assert "London" in response.text

def test_search_history():
    response = requests.get(f"{BASE_URL}/api/search_history/London")
    assert response.status_code == 200
    assert "count" in response.json()

@pytest.mark.parametrize("city", ["InvalidCity", ""])
def test_select_city_invalid(city):
    response = requests.post(f"{BASE_URL}/", data={"city": city})
    assert response.status_code == 200
    assert "Не удалось получить данные о погоде" in response.text