// Основной JavaScript для веб-интерфейса

// Глобальные переменные
let currentScenario = null;
let currentTimestamp = 0;
let canvas = null;
let ctx = null;

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    console.log('Инициализация интерфейса...');
    
    // Получаем элементы canvas
    canvas = document.getElementById('satelliteCanvas');
    if (canvas) {
        ctx = canvas.getContext('2d');
    }
    
    // Загружаем список файлов данных
    loadDataFiles();
    
    // Инициализируем карту
    if (ctx) {
        drawEmptyMap();
    }
});

// Загрузка списка файлов данных
async function loadDataFiles() {
    try {
        const response = await fetch('/api/data/files');
        const data = await response.json();
        
        const scenarios = document.querySelectorAll('.form-check-input');
        scenarios.forEach(checkbox => {
            checkbox.disabled = false;
        });
        
        console.log('Список файлов загружен:', data.files);
        
    } catch (error) {
        console.error('Ошибка при загрузке файлов:', error);
        showError('Ошибка при загрузке списка файлов');
    }
}

// Загрузка сценария (в данном случае просто выбираем файл)
function loadScenario() {
    console.log('Сценарий загружен');
}

// Расчет состояния сети
async function calculate() {
    // Получаем выбранный файл
    const selectedCheckbox = document.querySelector('.form-check-input:checked');
    if (!selectedCheckbox) {
        showError('Пожалуйста, выберите сценарий');
        return;
    }
    
    const filename = selectedCheckbox.value;
    const timestampInput = document.getElementById('timestamp');
    const timestamp = parseInt(timestampInput.value) || 0;
    
    try {
        showLoading('Расчет состояния сети...');
        currentTimestamp = timestamp;
        
        const response = await fetch('/api/calculate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                file: filename,
                timestamp: timestamp
            })
        });
        
        const data = await response.json();
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        console.log('Расчет завершен:', data);
        displayResults(data);
        
        // Отрисовываем карту
        if (ctx && data.result) {
            drawSatelliteMap(data.result);
        }
        
    } catch (error) {
        console.error('Ошибка при расчете:', error);
        showError('Ошибка при расчете: ' + error.message);
    }
}

// Отображение результатов
function displayResults(data) {
    const resultsDiv = document.getElementById('results-content');
    
    if (!data.result) {
        resultsDiv.innerHTML = '<p class="text-muted">Нет данных для отображения</p>';
        return;
    }
    
    let html = `
        <div class="results-content">
            <h5>Результаты расчета</h5>
            <p><strong>Время:</strong> ${data.timestamp} секунд</p>
            <p><strong>Спутники:</strong> ${data.result.satellites ? data.result.satellites.length : 0}</p>
            <p><strong>Связи:</strong> ${data.result.edges ? data.result.edges.length : 0}</p>
            
            <h6>Спутники:</h6>
            <div class="table-responsive">
                <table class="table table-striped table-hover">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Координаты (x, y, z)</th>
                            <th>Активен</th>
                        </tr>
                    </thead>
                    <tbody>
    `;
    
    if (data.result.satellites && data.result.satellites.length > 0) {
        data.result.satellites.forEach(sat => {
            html += `
                <tr>
                    <td>${sat.id}</td>
                    <td>(${sat.x_km.toFixed(2)}, ${sat.y_km.toFixed(2)}, ${sat.z_km.toFixed(2)})</td>
                    <td>${sat.active ? 'Да' : 'Нет'}</td>
                </tr>
            `;
        });
    } else {
        html += '<tr><td colspan="3">Нет данных о спутниках</td></tr>';
    }
    
    html += `
                </tbody>
            </table>
            </div>
            
            <h6>Связи:</h6>
            <div class="table-responsive">
                <table class="table table-striped table-hover">
                    <thead>
                        <tr>
                            <th>Спутник 1</th>
                            <th>Спутник 2</th>
                            <th>Расстояние (км)</th>
                        </tr>
                    </thead>
                    <tbody>
    `;
    
    if (data.result.edges && data.result.edges.length > 0) {
        data.result.edges.forEach(edge => {
            html += `
                <tr>
                    <td>${edge[0]}</td>
                    <td>${edge[1]}</td>
                    <td>${edge[2].toFixed(2)}</td>
                </tr>
            `;
        });
    } else {
        html += '<tr><td colspan="3">Нет данных о связях</td></tr>';
    }
    
    html += `
                </tbody>
            </table>
            </div>
        </div>
    `;
    
    resultsDiv.innerHTML = html;
}

// Отображение загрузки
function showLoading(message) {
    const resultsDiv = document.getElementById('results-content');
    resultsDiv.innerHTML = `<div class="loading">${message}...</div>`;
}

// Отображение ошибок
function showError(message) {
    const resultsDiv = document.getElementById('results-content');
    resultsDiv.innerHTML = `<div class="error">${message}</div>`;
}

// Отрисовка пустой карты
function drawEmptyMap() {
    if (!ctx) return;
    
    // Очищаем canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    // Рисуем фон
    ctx.fillStyle = '#f8f9fa';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    // Рисуем рамку
    ctx.strokeStyle = '#dee2e6';
    ctx.lineWidth = 2;
    ctx.strokeRect(0, 0, canvas.width, canvas.height);
    
    // Рисуем текст
    ctx.fillStyle = '#6c757d';
    ctx.font = '16px Arial';
    ctx.textAlign = 'center';
    ctx.fillText('Интерактивная карта спутниковой группировки', canvas.width/2, canvas.height/2);
}

// Отрисовка карты спутниковой группировки
function drawSatelliteMap(data) {
    if (!ctx || !data) return;
    
    // Очищаем canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    // Рисуем фон
    ctx.fillStyle = '#f8f9fa';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    // Рисуем рамку
    ctx.strokeStyle = '#dee2e6';
    ctx.lineWidth = 2;
    ctx.strokeRect(0, 0, canvas.width, canvas.height);
    
    if (!data.satellites || data.satellites.length === 0) {
        ctx.fillStyle = '#6c757d';
        ctx.font = '14px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('Нет данных о спутниках', canvas.width/2, canvas.height/2);
        return;
    }
    
    // Нарисуем Землю (как круг)
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    const earthRadius = Math.min(canvas.width, canvas.height) * 0.3;
    
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
    
    // Рисуем спутники
    const satellites = data.satellites;
    const maxRadius = earthRadius * 1.5;
    
    satellites.forEach((sat, index) => {
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
}

// Функция для отображения данных о спутниках
function displaySatelliteData(satellites) {
    const resultsDiv = document.getElementById('results-content');
    let html = '<div class="results-content"><h3>Спутники</h3><ul>';
    
    satellites.forEach(sat => {
        html += `<li>${sat.id}: (${sat.x_km}, ${sat.y_km}, ${sat.z_km}) - ${sat.active ? 'Активен' : 'Неактивен'}</li>`;
    });
    
    html += '</ul></div>';
    resultsDiv.innerHTML = html;
}

// Функция для отображения связей
function displayLinks(edges) {
    const resultsDiv = document.getElementById('results-content');
    let html = '<div class="results-content"><h3>Связи</h3><ul>';
    
    edges.forEach(edge => {
        html += `<li>${edge[0]} - ${edge[1]}: ${edge[2]} км</li>`;
    });
    
    html += '</ul></div>';
    resultsDiv.innerHTML = html;
}