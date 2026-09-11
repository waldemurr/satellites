import React, { useState, useEffect, useRef } from 'react';
import './App.css';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend
);

function App() {
  const [scenarios, setScenarios] = useState([]);
  const [selectedScenario, setSelectedScenario] = useState('');
  const [timestamp, setTimestamp] = useState(0);
  const [satelliteData, setSatelliteData] = useState(null);
  const [routeData, setRouteData] = useState(null);
  const [availabilityData, setAvailabilityData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const canvasRef = useRef(null);

  // Загрузка списка сценариев
  useEffect(() => {
    const loadScenarios = async () => {
      try {
        const response = await fetch('http://localhost:5002/api/data/files');
        const data = await response.json();
        setScenarios(data.files || []);
      } catch (err) {
        setError('Ошибка загрузки сценариев');
        console.error('Ошибка загрузки сценариев:', err);
      }
    };

    loadScenarios();
  }, []);

  // Рисование карты спутников
  const drawSatelliteMap = (data) => {
    const canvas = canvasRef.current;
    if (!canvas || !data) return;

    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    
    // Очистка канваса
    ctx.clearRect(0, 0, width, height);
    
    // Рисуем фон
    ctx.fillStyle = '#f8f9fa';
    ctx.fillRect(0, 0, width, height);
    
    // Рисуем Землю
    const centerX = width / 2;
    const centerY = height / 2;
    const earthRadius = Math.min(width, height) * 0.3;
    
    ctx.beginPath();
    ctx.arc(centerX, centerY, earthRadius, 0, Math.PI * 2);
    ctx.fillStyle = '#4a90e2';
    ctx.fill();
    ctx.strokeStyle = '#357abd';
    ctx.lineWidth = 2;
    ctx.stroke();
    
    // Рисуем центр Земли
    ctx.beginPath();
    ctx.arc(centerX, centerY, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#ff6b6b';
    ctx.fill();
    
    if (!data.satellites || data.satellites.length === 0) {
      ctx.fillStyle = '#6c757d';
      ctx.font = '14px Arial';
      ctx.textAlign = 'center';
      ctx.fillText('Нет данных о спутниках', width/2, height/2);
      return;
    }
    
    // Рисуем спутники
    const maxRadius = earthRadius * 1.5;
    
    data.satellites.forEach((sat, index) => {
      if (sat.active) {
        // Преобразуем координаты для отображения (простое масштабирование)
        const x = centerX + (sat.x_km / 10000) * maxRadius;
        const y = centerY + (sat.y_km / 10000) * maxRadius;
        
        // Рисуем спутник
        ctx.beginPath();
        ctx.arc(x, y, 6, 0, Math.PI * 2);
        ctx.fillStyle = '#ff6b6b';
        ctx.fill();
        ctx.strokeStyle = '#ff5252';
        ctx.lineWidth = 2;
        ctx.stroke();
        
        // Добавляем подпись
        ctx.fillStyle = '#333';
        ctx.font = '10px Arial';
        ctx.textAlign = 'center';
        ctx.fillText(sat.id, x, y - 10);
      }
    });
    
    // Рисуем связи между спутниками (если есть)
    if (data.edges && data.edges.length > 0) {
      data.edges.forEach(edge => {
        // Найдем координаты спутников
        const sat1 = data.satellites.find(s => s.id === edge[0]);
        const sat2 = data.satellites.find(s => s.id === edge[1]);
        
        if (sat1 && sat2 && sat1.active && sat2.active) {
          // Преобразуем координаты
          const x1 = centerX + (sat1.x_km / 10000) * maxRadius;
          const y1 = centerY + (sat1.y_km / 10000) * maxRadius;
          const x2 = centerX + (sat2.x_km / 10000) * maxRadius;
          const y2 = centerY + (sat2.y_km / 10000) * maxRadius;
          
          // Рисуем линию связи
          ctx.beginPath();
          ctx.moveTo(x1, y1);
          ctx.lineTo(x2, y2);
          ctx.strokeStyle = '#4ecdc4';
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      });
    }
  };

  // Расчет состояния сети
  const handleCalculate = async () => {
    if (!selectedScenario) {
      setError('Пожалуйста, выберите сценарий');
      return;
    }

    setIsLoading(true);
    setError('');

    try {
      const response = await fetch(`http://localhost:5002/api/calculate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          file: selectedScenario,
          timestamp: timestamp
        })
      });

      const data = await response.json();
      
      if (data.error) {
        throw new Error(data.error);
      }

      setSatelliteData(data.result);
      drawSatelliteMap(data.result);
      
    } catch (err) {
      setError(`Ошибка расчета: ${err.message}`);
      console.error('Ошибка расчета:', err);
    } finally {
      setIsLoading(false);
    }
  };

  // Получение маршрута
  const handleGetRoute = async () => {
    if (!selectedScenario) {
      setError('Пожалуйста, выберите сценарий');
      return;
    }

    setIsLoading(true);
    setError('');

    try {
      // Пример: получение маршрута для первого клиента и шлюза
      const clients = ['C65', 'C70', 'C72'];
      const gateways = ['G_MUR'];
      const client = clients[0];
      const gateway = gateways[0];
      
      const response = await fetch(`http://localhost:5002/api/route/${selectedScenario}/${client}/${gateway}`);
      const data = await response.json();
      
      if (data.error) {
        throw new Error(data.error);
      }

      setRouteData(data);
      
    } catch (err) {
      setError(`Ошибка маршрутизации: ${err.message}`);
      console.error('Ошибка маршрутизации:', err);
    } finally {
      setIsLoading(false);
    }
  };

  // Получение доступности
  const handleGetAvailability = async () => {
    if (!selectedScenario) {
      setError('Пожалуйста, выберите сценарий');
      return;
    }

    setIsLoading(true);
    setError('');

    try {
      const response = await fetch(`http://localhost:5002/api/availability/${selectedScenario}`);
      const data = await response.json();
      
      if (data.error) {
        throw new Error(data.error);
      }

      setAvailabilityData(data);
      
    } catch (err) {
      setError(`Ошибка расчета доступности: ${err.message}`);
      console.error('Ошибка доступности:', err);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>Проектирование устойчивой спутниковой группировки</h1>
        <p>Сервис для анализа доступности связи в северных районах</p>
      </header>

      <main className="container">
        <div className="row">
          <div className="col-lg-4">
            <div className="card mb-4">
              <div className="card-header bg-secondary text-white">
                <h5 className="mb-0">Управление данными</h5>
              </div>
              <div className="card-body">
                <div className="mb-3">
                  <h6 className="mb-3">Выберите сценарий:</h6>
                  <div className="form-group mb-3">
                    <select 
                      className="form-select" 
                      value={selectedScenario} 
                      onChange={(e) => setSelectedScenario(e.target.value)}
                    >
                      <option value="">Выберите файл</option>
                      {scenarios.map((scenario) => (
                        <option key={scenario} value={scenario}>{scenario}</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group mb-3">
                    <label htmlFor="timestamp" className="form-label">Время (сек):</label>
                    <input 
                      type="number" 
                      className="form-control" 
                      id="timestamp" 
                      value={timestamp} 
                      onChange={(e) => setTimestamp(parseInt(e.target.value) || 0)}
                      min="0"
                    />
                  </div>
                  <div className="d-grid gap-2">
                    <button 
                      className="btn btn-primary" 
                      onClick={handleCalculate}
                      disabled={isLoading}
                    >
                      {isLoading ? 'Расчет...' : 'Рассчитать состояние сети'}
                    </button>
                    <button 
                      className="btn btn-success" 
                      onClick={handleGetRoute}
                      disabled={isLoading}
                    >
                      {isLoading ? 'Маршрутизация...' : 'Получить маршрут'}
                    </button>
                    <button 
                      className="btn btn-info" 
                      onClick={handleGetAvailability}
                      disabled={isLoading}
                    >
                      {isLoading ? 'Доступность...' : 'Расчет доступности'}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {error && (
              <div className="alert alert-danger" role="alert">
                {error}
              </div>
            )}

            {satelliteData && (
              <div className="card mb-4">
                <div className="card-header bg-secondary text-white">
                  <h5 className="mb-0">Результаты расчета</h5>
                </div>
                <div className="card-body">
                  <p><strong>Время:</strong> {satelliteData.timestamp} секунд</p>
                  <p><strong>Спутники:</strong> {satelliteData.result?.satellites?.length || 0}</p>
                  <p><strong>Связи:</strong> {satelliteData.result?.edges?.length || 0}</p>
                </div>
              </div>
            )}

            {routeData && (
              <div className="card mb-4">
                <div className="card-header bg-secondary text-white">
                  <h5 className="mb-0">Маршрут</h5>
                </div>
                <div className="card-body">
                  <p><strong>Клиент:</strong> {routeData.routes ? Object.keys(routeData.routes)[0] : 'N/A'}</p>
                  <p><strong>Доступность:</strong> {routeData.routes ? routeData.routes[Object.keys(routeData.routes)[0]]?.availability : 'N/A'}</p>
                </div>
              </div>
            )}

            {availabilityData && (
              <div className="card mb-4">
                <div className="card-header bg-secondary text-white">
                  <h5 className="mb-0">Доступность связи</h5>
                </div>
                <div className="card-body">
                  <p><strong>Средняя доступность:</strong> {availabilityData.clients ? Object.values(availabilityData.clients)[0]?.availability : 'N/A'}</p>
                  <p><strong>Целевой уровень:</strong> {availabilityData.target_availability}</p>
                </div>
              </div>
            )}
          </div>

          <div className="col-lg-8">
            <div className="card mb-4">
              <div className="card-header bg-secondary text-white">
                <h5 className="mb-0">Визуализация спутниковой группировки</h5>
              </div>
              <div className="card-body">
                <div className="map-container">
                  <canvas 
                    ref={canvasRef} 
                    width={600} 
                    height={400}
                    style={{ border: '1px solid #dee2e6', borderRadius: '8px' }}
                  />
                  <p className="text-center mt-3 text-muted">
                    Интерактивная карта спутниковой группировки
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;