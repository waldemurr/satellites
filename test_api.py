#!/usr/bin/env python3
"""
Простой тест API
"""

import os
import sys
sys.path.insert(0, '/home/redfox/programming/python/satellites/backend')

print("Тест запуска API...")

try:
    from app.main import create_app
    
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
            print(f"  Расчетный модуль: {data.get('calculation_module')}")
            print(f"  Расширенные модули: {data.get('extended_modules')}")
    
    # Тестируем список файлов
    response = client.get('/api/data/files')
    print(f"✓ Список файлов: {response.status_code}")
    if response.status_code == 200:
        data = response.get_json()
        print(f"  Найдено файлов: {len(data.get('files', []))}")
        for f in data.get('files', [])[:3]:
            print(f"  - {f}")
    
    print("✓ Все тесты пройдены успешно!")
    
except Exception as e:
    print(f"✗ Ошибка: {e}")
    import traceback
    traceback.print_exc()