#!/usr/bin/env python3
"""Простой тест API — проверяет создание приложения и базовые эндпоинты."""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, 'backend'))

print("Тест запуска API...")

try:
    from main import create_app

    # Создаем приложение
    app = create_app()
    print("✓ Приложение создано успешно")

    # Тестируем health endpoint
    with app.test_client() as client:
        response = client.get('/api/health')
        print(f"✓ Health check: {response.status_code}")
        if response.status_code == 200:
            data = response.get_json()
            print(f"  Статус: {data.get('status')}")
            print(f"  Расчётные модули доступны: {data.get('modules_available')}")

        # Главная страница (фронтенд)
        response = client.get('/')
        print(f"✓ Главная страница /: {response.status_code}")

        # Статика
        response = client.get('/static/app.js')
        print(f"✓ Статика /static/app.js: {response.status_code}")

    # Тестируем список файлов
    with app.test_client() as client:
        response = client.get('/api/data/files')
        print(f"✓ Список файлов: {response.status_code}")
        if response.status_code == 200:
            data = response.get_json()
            print(f"  Найдено файлов: {len(data.get('files', []))}")
            for f in data.get('files', [])[:3]:
                print(f"  - {f}")

        # Мета сценария
        files = data.get('files', []) if response.status_code == 200 else []
        if files:
            response = client.get(f"/api/data/{files[0]}/meta")
            print(f"✓ Мета сценария {files[0]}: {response.status_code}")
            if response.status_code == 200:
                meta = response.get_json()
                print(f"  Плоскостей: {len(meta.get('planes', []))}, "
                      f"пунктов: {len(meta.get('ground_sites', []))}")

        # Снапшот в момент t=0
        if files:
            response = client.post('/api/calculate',
                                   json={'file': files[0], 'timestamp': 0})
            print(f"✓ Расчёт снапшота (t=0): {response.status_code}")
            if response.status_code == 200:
                snap = response.get_json()['result']
                print(f"  Спутников: {len(snap.get('satellites', []))}, "
                      f"связей: {len(snap.get('edges', []))}")

    print("✓ Все тесты пройдены успешно!")

except Exception as e:
    print(f"✗ Ошибка: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
