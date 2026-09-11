"""
Тесты для веб-приложения
"""
import unittest
import json
from app.main import create_app

class TestApp(unittest.TestCase):
    def setUp(self):
        """Настройка перед тестами"""
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
    
    def test_health_check(self):
        """Тест проверки состояния сервиса"""
        response = self.client.get('/api/health')
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue('status' in data)
        self.assertTrue('calculation_module' in data)
    
    def test_index_route(self):
        """Тест главной страницы"""
        response = self.client.get('/')
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('message', data)
    
    def test_data_files_route(self):
        """Тест получения списка файлов данных"""
        response = self.client.get('/api/data/files')
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('files', data)
    
    def test_invalid_file_route(self):
        """Тест запроса несуществующего файла"""
        response = self.client.get('/api/data/invalid_file.json')
        # Ожидаем ошибку, так как файла не существует
        self.assertIn('error', json.loads(response.data))

if __name__ == '__main__':
    unittest.main()