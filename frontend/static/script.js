// Основной JavaScript для веб-интерфейса

// Глобальные переменные
let currentScenario = null;
let currentTimestamp = 0;

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    console.log('Инициализация интерфейса...');
    loadDataFiles();
});

// Загрузка списка файлов данных
async function loadDataFiles() {
    try {
        const response = await fetch('/api/data/files');
        const data = await response.json();
        
        const fileSelect = document.getElementById('data-file');
        fileSelect.innerHTML = '<option value="">Выберите файл</option>';
        
        data.files.forEach(file => {
            const option = document.createElement('option');
            option.value = file;
            option.textContent = file;
            fileSelect.appendChild(option);
        });
        
        console.log('Список файлов загружен:', data.files);
    } catch (error) {
        console.error('Ошибка при загрузке файлов:', error);
        showError('Ошибка при загрузке списка файлов');
    }
}

// Загрузка сценария
async function loadScenario() {
    const fileSelect = document.getElementById('data-file');
    const filename = fileSelect.value;
    
    if (!filename) {
        showResults('Пожалуйста, выберите файл данных');
        return;
    }
    
    try {
        showLoading('Загрузка данных...');
        const response = await fetch(`/api/data/${filename}`);
        const data = await response.json();
        
        currentScenario = data;
        currentTimestamp = 0;
        document.getElementById('timestamp').value = 0;
        
        console.log('Сценарий загружен:', filename);
        showResults('Сценарий успешно загружен. Нажмите "Рассчитать" для анализа.');
        
        // Отрисовка карты (в будущем)
        // drawMap(data);
        
    } catch (error) {
        console.error('Ошибка при загрузке сценария:', error);
        showError('Ошибка при загрузке сценария: ' + error.message);
    }
}

// Расчет состояния сети
async function calculate() {
    const fileSelect = document.getElementById('data-file');
    const filename = fileSelect.value;
    const timestampInput = document.getElementById('timestamp');
    
    if (!filename) {
        showError('Пожалуйста, выберите файл данных');
        return;
    }
    
    const timestamp = parseInt(timestampInput.value) || 0;
    
    try {
        showLoading('Расчет состояния сети...');
        
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
        
        currentTimestamp = timestamp;
        console.log('Расчет завершен:', data);
        displayResults(data);
        
    } catch (error) {
        console.error('Ошибка при расчете:', error);
        showError('Ошибка при расчете: ' + error.message);
    }
}

// Отображение результатов
function displayResults(data) {
    const resultsDiv = document.getElementById('results-content');
    
    if (!data.result) {
        resultsDiv.innerHTML = '<p>Нет данных для отображения</p>';
        return;
    }
    
    let html = `
        <div class="results-content">
            <h3>Результаты расчета</h3>
            <p><strong>Время:</strong> ${data.timestamp} секунд</p>
            <p><strong>Спутники:</strong> ${data.result.satellites ? data.result.satellites.length : 0}</p>
            <p><strong>Связи:</strong> ${data.result.edges ? data.result.edges.length : 0}</p>
            
            <h4>Спутники:</h4>
            <table class="data-table">
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
            
            <h4>Связи:</h4>
            <table class="data-table">
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

// Отображение результатов
function showResults(message) {
    const resultsDiv = document.getElementById('results-content');
    resultsDiv.innerHTML = `<p>${message}</p>`;
}

// Отрисовка карты (заглушка)
function drawMap(scenario) {
    const mapContainer = document.getElementById('satellite-map');
    mapContainer.innerHTML = '<p>Карта будет отображена здесь</p>';
    
    console.log('Отрисовка карты для сценария:', scenario.meta?.title || 'Без названия');
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