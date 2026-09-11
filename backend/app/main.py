"""
Основной модуль веб-приложения для проектирования спутниковой группировки
"""
import os
import json
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import numpy as np

# Импортируем расчетный модуль
try:
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), 'module'))
    from geometry import load, validate, snapshot
    CALCULATION_MODULE_AVAILABLE = True
except ImportError:
    CALCULATION_MODULE_AVAILABLE = False
    print("Расчетный модуль не доступен")

# Настройка директорий
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

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
            'calculation_module': CALCULATION_MODULE_AVAILABLE
        })
    
    @app.route('/api/data/files')
    def get_data_files():
        """Получение списка доступных файлов данных"""
        try:
            data_dir = os.path.join(BASE_DIR, 'data')
            files = [f for f in os.listdir(data_dir) if f.endswith('.json')]
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
            file_path = os.path.join(BASE_DIR, 'data', filename)
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
            file_path = os.path.join(BASE_DIR, 'data', filename)
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
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5002)