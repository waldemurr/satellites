"""
Конфигурация веб-приложения
"""
import os

class Config:
    # Базовая конфигурация
    DEBUG = False
    TESTING = False
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    
    # Настройки данных
    DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
    MODULE_DIR = os.path.join(os.path.dirname(__file__), '..', 'module')
    
    # Настройки расчётов
    DEFAULT_TIMESTEP = 120  # секунды
    DEFAULT_HORIZON = 86400  # секунды (сутки)
    
    # Настройки API
    API_VERSION = 'v1'
    
    @classmethod
    def init_app(cls, app):
        """Инициализация приложения"""
        pass

class DevelopmentConfig(Config):
    DEBUG = True
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-for-development'

class ProductionConfig(Config):
    DEBUG = False

# Конфигурации по окружению
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}