#!/usr/bin/env python3
"""
Тестирование модулей напрямую
"""

import sys
import os

# Добавляем путь к модулям
sys.path.insert(0, '/home/redfox/programming/python/satellites/backend/module')

try:
    from geometry import load, validate, snapshot
    print("✓ geometry.py успешно импортирован")
    
    # Проверим, что можно выполнить простой тест
    print("✓ Основные функции доступны")
    
    # Проверим расширенные модули
    import importlib.util
    
    # Проверка routing.py
    routing_spec = importlib.util.spec_from_file_location("routing", "/home/redfox/programming/python/satellites/backend/module/routing.py")
    routing = importlib.util.module_from_spec(routing_spec)
    routing_spec.loader.exec_module(routing)
    print("✓ routing.py успешно импортирован")
    
    # Проверка availability.py
    availability_spec = importlib.util.spec_from_file_location("availability", "/home/redfox/programming/python/satellites/backend/module/availability.py")
    availability = importlib.util.module_from_spec(availability_spec)
    availability_spec.loader.exec_module(availability)
    print("✓ availability.py успешно импортирован")
    
    # Проверка monte_carlo.py
    monte_carlo_spec = importlib.util.spec_from_file_location("monte_carlo", "/home/redfox/programming/python/satellites/backend/module/monte_carlo.py")
    monte_carlo = importlib.util.module_from_spec(monte_carlo_spec)
    monte_carlo_spec.loader.exec_module(monte_carlo)
    print("✓ monte_carlo.py успешно импортирован")
    
    print("Все модули успешно импортированы!")
    
except Exception as e:
    print(f"Ошибка импорта: {e}")
    import traceback
    traceback.print_exc()