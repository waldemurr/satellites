"""
Основной модуль веб-приложения для проектирования спутниковой группировки
"""
import os
import json
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import numpy as np

# Настройка директорий
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Для Docker и правильного пути к данным
DATA_DIR = os.path.join(BASE_DIR, '..', 'data')
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

# Импортируем расчетный модуль
try:
    # Добавляем путь к модулям
    sys.path.insert(0, os.path.join(BASE_DIR, 'module'))
    
    # Импортируем основные модули
    from geometry import load, validate, snapshot
    CALCULATION_MODULE_AVAILABLE = True
    
    # Импортируем дополнительные модули для расширенной функциональности
    import importlib.util
    
    # Импорт модулей с проверкой
    routing_spec = importlib.util.spec_from_file_location("routing", os.path.join(BASE_DIR, 'module', 'routing.py'))
    routing = importlib.util.module_from_spec(routing_spec)
    routing_spec.loader.exec_module(routing)
    
    availability_spec = importlib.util.spec_from_file_location("availability", os.path.join(BASE_DIR, 'module', 'availability.py'))
    availability = importlib.util.module_from_spec(availability_spec)
    availability_spec.loader.exec_module(availability)
    
    monte_carlo_spec = importlib.util.spec_from_file_location("monte_carlo", os.path.join(BASE_DIR, 'module', 'monte_carlo.py'))
    monte_carlo = importlib.util.module_from_spec(monte_carlo_spec)
    monte_carlo_spec.loader.exec_module(monte_carlo)
    
    EXTENDED_MODULES_AVAILABLE = True
    
except ImportError as e:
    CALCULATION_MODULE_AVAILABLE = False
    EXTENDED_MODULES_AVAILABLE = False
    print(f"Расчетный модуль не доступен: {e}")

def create_app():
    """Создание Flask приложения"""
    app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
    CORS(app)
    
    @app.route('/')
    def index():
        """Главная страница"""
        return render_template('index.html')
    
    @app.route('/api/health')
    def health():
        """Проверка состояния сервиса"""
        return jsonify({
            'status': 'healthy',
            'calculation_module': CALCULATION_MODULE_AVAILABLE,
            'extended_modules': EXTENDED_MODULES_AVAILABLE
        })
    
    @app.route('/api/data/files')
    def get_data_files():
        """Получение списка доступных файлов данных"""
        try:
            # Проверяем, существует ли директория
            if os.path.exists(DATA_DIR):
                files = [f for f in os.listdir(DATA_DIR) if f.endswith('.json')]
            else:
                files = []
            return jsonify({
                'files': files
            })
        except Exception as e:
            return jsonify({
                'error': str(e)
            }), 500
    
    @app.route('/api/data/<filename>')
    def get_data_file(filename):
        """Получение содержимого файла данных"""
        try:
            file_path = os.path.join(DATA_DIR, filename)
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        except Exception as e:
            return jsonify({
                'error': f'Ошибка загрузки файла {filename}: {str(e)}'
            }), 500
    
    @app.route('/api/calculate', methods=['POST'])
    def calculate():
        """Расчет состояния сети"""
        try:
            if not CALCULATION_MODULE_AVAILABLE:
                return jsonify({
                    'error': 'Расчетный модуль недоступен'
                }), 500
                
            data = request.get_json()
            filename = data.get('file')
            timestamp = data.get('timestamp', 0)
            
            # Загружаем файл
            file_path = os.path.join(DATA_DIR, filename)
            scenario = load(file_path)
            
            # Выполняем расчет
            result = snapshot(scenario, timestamp)
            
            return jsonify({
                'result': result,
                'timestamp': timestamp
            })
        except Exception as e:
            return jsonify({
                'error': f'Ошибка расчета: {str(e)}'
            }), 500
    
    @app.route('/api/validate', methods=['POST'])
    def validate_scenario():
        """Валидация сценария"""
        try:
            data = request.get_json()
            # Проверяем, что это JSON-данные сценария
            scenario = data.get('scenario')
            if not scenario:
                return jsonify({
                    'error': 'Не указан сценарий'
                }), 400
                
            # Выполняем валидацию
            errors = validate(scenario)
            
            if errors:
                return jsonify({
                    'valid': False,
                    'errors': errors
                })
            else:
                return jsonify({
                    'valid': True,
                    'errors': []
                })
        except Exception as e:
            return jsonify({
                'error': f'Ошибка валидации: {str(e)}'
            }), 500
    
    @app.route('/api/route/<filename>/<client_id>/<gateway_id>')
    def calculate_route(filename, client_id, gateway_id):
        """Расчет маршрута между клиентом и шлюзом"""
        try:
            if not EXTENDED_MODULES_AVAILABLE:
                return jsonify({
                    'error': 'Расширенные модули недоступны'
                }), 500
                
            file_path = os.path.join(DATA_DIR, filename)
            scenario = load(file_path)
            
            # Используем routing.py для маршрутизации
            result = routing.scenario_routing_report(scenario, strategy='hops')
            return jsonify(result)
        except Exception as e:
            return jsonify({
                'error': f'Ошибка маршрутизации: {str(e)}'
            }),  500
    
    @app.route('/api/availability/<filename>')
    def calculate_availability(filename):
        """Расчет доступности связи"""
        try:
            if not EXTENDED_MODULES_AVAILABLE:
                return jsonify({
                    'error': 'Расширенные модули недоступны'
                }), 500
                
            file_path = os.path.join(DATA_DIR, filename)
            scenario = load(file_path)
            
            # Используем availability.py для расчета доступности
            result = availability.scenario_availability(scenario)
            return jsonify(result)
        except Exception as e:
            return jsonify({
                'error': f'Ошибка расчета доступности: {str(e)}'
            }), 500
    
    @app.route('/api/monte-carlo/<filename>')
    def monte_carlo_analysis(filename):
        """Монте-Карло анализ устойчивости"""
        try:
            if not EXTENDED_MODULES_AVAILABLE:
                return jsonify({
                    'error': 'Расширенные модули недоступны'
                }), 500
                
            file_path = os.path.join(DATA_DIR, filename)
            scenario = load(file_path)
            
            # Используем monte_carlo.py для анализа рисков
            result = monte_carlo.monte_carlo_risk(scenario, n_trials=100)
            return jsonify(result)
        except Exception as e:
            return jsonify({
                'error': f'Ошибка Монте-Карло анализа: {str(e)}'
            }), 500
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5002)