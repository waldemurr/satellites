#!/usr/bin/env python3
"""
Простой скрипт для проверки функциональности приложения
"""

import requests
import json

def test_api():
    """Тестирование API"""
    base_url = "http://localhost:5001"
    
    print("=== Тестирование API ===")
    
    # 1. Проверка состояния сервиса
    print("\n1. Проверка состояния сервиса...")
    try:
        response = requests.get(f"{base_url}/api/health")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Статус: {data['status']}")
            print(f"✓ Расчетный модуль: {data['calculation_module']}")
        else:
            print(f"✗ Ошибка: {response.status_code}")
    except Exception as e:
        print(f"✗ Ошибка при проверке состояния: {e}")
    
    # 2. Проверка списка файлов
    print("\n2. Проверка списка файлов...")
    try:
        response = requests.get(f"{base_url}/api/data/files")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Найдено файлов: {len(data['files'])}")
            for file in data['files']:
                print(f"  - {file}")
        else:
            print(f"✗ Ошибка: {response.status_code}")
    except Exception as e:
        print(f"✗ Ошибка при получении файлов: {e}")
    
    # 3. Проверка главной страницы
    print("\n3. Проверка главной страницы...")
    try:
        response = requests.get(f"{base_url}/")
        if response.status_code == 200:
            print("✓ Главная страница загружена успешно")
            if "Проектирование устойчивой спутниковой группировки" in response.text:
                print("✓ Содержимое страницы корректно")
            else:
                print("✗ Содержимое страницы не совпадает")
        else:
            print(f"✗ Ошибка загрузки страницы: {response.status_code}")
    except Exception as e:
        print(f"✗ Ошибка при проверке главной страницы: {e}")
    
    # 4. Проверка статических файлов
    print("\n4. Проверка статических файлов...")
    try:
        response = requests.get(f"{base_url}/static/style.css")
        if response.status_code == 200:
            print("✓ CSS файл загружен успешно")
        else:
            print(f"✗ Ошибка CSS: {response.status_code}")
            
        response = requests.get(f"{base_url}/static/script.js")
        if response.status_code == 200:
            print("✓ JS файл загружен успешно")
        else:
            print(f"✗ Ошибка JS: {response.status_code}")
    except Exception as e:
        print(f"✗ Ошибка при проверке статических файлов: {e}")
    
    print("\n=== Тестирование завершено ===")

if __name__ == "__main__":
    test_api()