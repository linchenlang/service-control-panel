// ---------- 全局 ----------
let currentDeviceIp = null;
let lastServiceStates = {};
let pendingStopIds = new Set();
let stopTimestamps = new Map();
let trendChart = null;
let currentTrendMode = 'net';
let netHistory = [];
let diskIoHistory = {};
let currentDisk = null;

let serviceRefreshTimer = null;
let monitorRefreshTimer = null;
let trafficRefreshTimer = null;
let sensorsRefreshTimer = null;
let trendRefreshTimer = null;
let currentLogServiceId = null;

// ---------- Toast 队列 ----------
let toastQueue = [];
let isShowingToast = false;

function showToast(message, type = 'info') {
    toastQueue.push({ message, type });
    if (!isShowingToast) processToastQueue();
}

function processToastQueue() {
    if (toastQueue.length === 0) {
        isShowingToast = false;
        return;
    }
    isShowingToast = true;
    const { message, type } = toastQueue.shift();
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerText = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.remove();
        processToastQueue();
    }, 2000);
}

// ---------- 全局 fetch 封装 ----------
async function fetchWithError(url, options = {}) {
    try {
        const response = await fetch(url, options);
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`HTTP ${response.status}: ${text.substring(0, 200)}`);
        }
        return response;
    } catch (error) {
        console.error('API请求失败:', error);
        showAlertModal(`服务器连接失败，请检查网络或面板状态。\n错误：${error.message}`);
        throw error;
    }
}

// ---------- 自定义确认弹窗 ----------
function showConfirmModal(message, onConfirm) {
    const modal = document.getElementById('alertModal');
    const content = document.getElementById('alertModalContent');
    content.innerHTML = `${message}<br><div style="margin-top:1rem;">
        <button id="confirmYes" style="background:#c0392b; color:white; border:none; padding:0.3rem 1rem; border-radius:1rem;">确定</button>
        <button id="confirmNo" style="background:#666; color:white; border:none; padding:0.3rem 1rem; border-radius:1rem;">取消</button>
    </div>`;
    modal.style.display = 'flex';
    document.getElementById('confirmYes').onclick = () => {
        modal.style.display = 'none';
        onConfirm();
    };
    document.getElementById('confirmNo').onclick = () => modal.style.display = 'none';
}

function showAlertModal(message) {
    const modal = document.getElementById('alertModal');
    document.getElementById('alertModalContent').innerHTML = message;
    modal.style.display = 'flex';
}
function closeAlertModal() { document.getElementById('alertModal').style.display = 'none'; }
function closeModal() { document.getElementById('logModal').style.display = 'none'; }
function closeIpconfigModal() { document.getElementById('ipconfigModal').style.display = 'none'; }
function scrollLogToBottom() { const el = document.getElementById('logContent'); if(el) el.scrollTop = el.scrollHeight; }
function escapeHtml(str) { if (!str) return ''; return str.replace(/[&<>]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;'})[m]); }

async function fetchMyIp() {
    try { const res = await fetchWithError('/api/my_ip'); const data = await res.json(); currentDeviceIp = data.ip; } catch(e) {}
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(tab => tab.style.display = 'none');
    document.getElementById(`${tabId}-tab`).style.display = 'block';
    document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
    document.querySelector(`.nav-item[data-tab="${tabId}"]`).classList.add('active');
    if (tabId === 'services') refreshServices();
    if (tabId === 'traffic') { refreshTrafficCards(); updateAllTraffic(); }
    if (tabId === 'monitor') refreshMonitor();
    if (tabId === 'oplogs') loadOperationHistory();
    if (tabId === 'dashboard') { refreshSensors(); updateNetworkCard(); updateIpCard(); updateDisks(); loadRisksPreview(); }
    if (tabId === 'settings') { loadSettings(); loadServiceConfigs(); loadDeploymentConfig(); }
    if (tabId === 'banip') loadBannedIps();
    if (tabId === 'risks') loadRisks();
}

// ---------- 部署配置管理 ----------
async function loadDeploymentConfig() {
    try {
        const res = await fetchWithError('/api/deployment_config');
        const config = await res.json();
        document.getElementById('deployEnvironment').value = config.environment || 'intranet';
        document.getElementById('deployHasPublicIp').checked = config.has_public_ip === true;
        document.getElementById('deployFirewallEnabled').checked = config.firewall_enabled !== false;
        document.getElementById('deployHttpsEnabled').checked = config.https_enabled === true;
        document.getElementById('deployAllowExternal').checked = config.allow_external_access === true;
        document.getElementById('deployAutoBanIp').checked = config.auto_ban_ip !== false;
        document.getElementById('deployRiskInterval').value = config.risk_check_interval || 60;
        document.getElementById('deployAdminEmail').value = config.admin_email || '';
        document.getElementById('deployNotes').value = config.notes || '';
        if (config.configured === false) {
            showAlertModal('请先完成部署环境配置，以便风险检测模块提供准确的建议。\n您可以在“设置”页面中找到“部署环境配置”区域。');
        }
    } catch (e) {
        console.error('加载部署配置失败', e);
    }
}

async function saveDeploymentConfig() {
    const data = {
        environment: document.getElementById('deployEnvironment').value,
        has_public_ip: document.getElementById('deployHasPublicIp').checked,
        firewall_enabled: document.getElementById('deployFirewallEnabled').checked,
        https_enabled: document.getElementById('deployHttpsEnabled').checked,
        allow_external_access: document.getElementById('deployAllowExternal').checked,
        notes: document.getElementById('deployNotes').value
    };
    try {
        const res = await fetchWithError('/api/deployment_config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await res.json();
        if (result.success) {
            showToast('部署配置已更新', 'success');
            if (document.querySelector('.nav-item.active').dataset.tab === 'dashboard') {
                loadRisksPreview();
            }
        } else {
            showAlertModal('保存失败：' + (result.message || '未知错误'));
        }
    } catch (e) {
        showAlertModal('保存失败：' + e.message);
    }
}

// ---------- 原有函数 ----------
async function loadOperationHistory() {
    const res = await fetchWithError('/api/operation_history?limit=200');
    const records = await res.json();
    let html = '<table style="width:100%; border-collapse:collapse;"><thead><tr><th>时间</th><th>服务</th><th>动作</th><th>来源IP</th></tr></thead><tbody>';
    for(let r of records) {
        let actionText = r.action;
        if (actionText === 'maintenance_on') actionText = '维护开启';
        else if (actionText === 'maintenance_off') actionText = '维护关闭';
        else if (actionText === 'start') actionText = '启动';
        else if (actionText === 'stop') actionText = '停止';
        const ipStyle = (r.source_ip !== '127.0.0.1') ? 'color: #c0392b; font-weight: bold;' : '';
        html += `<tr><td style="padding:8px;">${r.datetime}</td><td>${escapeHtml(r.service_name)}</td><td style="color:${r.action==='stop'?'#c0392b':'#2b7e3a'}">${actionText}</td><td style="${ipStyle}">${escapeHtml(r.source_ip)}</td></tr>`;
    }
    html += '</tbody></table>';
    document.getElementById('historyTable').innerHTML = html;
}

function drawSmallGauge(canvasId, percent, customColor = null) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    const centerX = w/2, centerY = h/2;
    const radius = Math.min(w, h) * 0.32;
    const startAngle = Math.PI * 0.75, endAngle = Math.PI * 2.25;
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius, startAngle, endAngle);
    ctx.strokeStyle = '#ddd';
    ctx.lineWidth = 8;
    ctx.stroke();
    const angle = startAngle + (endAngle - startAngle) * (percent / 100);
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius, startAngle, angle);
    let color = customColor;
    if (!color) color = percent > 90 ? '#e74c3c' : (percent > 70 ? '#f39c12' : '#2ecc71');
    ctx.strokeStyle = color;
    ctx.lineWidth = 8;
    ctx.stroke();
    const fontSize = Math.floor(radius * 0.45);
    ctx.font = `bold ${fontSize}px "Segoe UI", "FZXiaoBiaoSong", monospace`;
    ctx.fillStyle = color;
    const text = `${percent}%`;
    const textWidth = ctx.measureText(text).width;
    ctx.fillText(text, centerX - textWidth/2, centerY + fontSize/3);
}

async function updateNetworkCard() {
    const container = document.getElementById('networkCardContainer');
    if (!container) return;
    const sensorRes = await fetchWithError('/api/sensors');
    const sensorData = await sensorRes.json();
    let netHtml = `<div class="sensor-left"><div class="sensor-title">网络接口</div>`;
    if (sensorData.network_interfaces && sensorData.network_interfaces.length) {
        for (let iface of sensorData.network_interfaces) {
            netHtml += `<div class="sensor-detail">${iface.name} (${iface.type}): ${iface.ip}</div>`;
        }
    } else {
        netHtml += `<div class="sensor-detail">未获取到网络接口信息</div>`;
    }
    netHtml += `</div>`;
    container.innerHTML = netHtml;
}

async function updateIpCard() {
    const container = document.getElementById('ipCardContainer');
    if (!container) return;

    let publicIp = '加载中...';
    try {
        const publicRes = await fetchWithError('/api/public_ip');
        const publicData = await publicRes.json();
        publicIp = publicData.ip || '无公网IP地址';
    } catch(e) {
        publicIp = '获取失败';
    }

    let addresses = [];
    try {
        const res = await fetchWithError('/api/ip_detailed');
        const data = await res.json();
        if (data.success && data.addresses) {
            addresses = data.addresses;
        } else {
            const sensorRes = await fetchWithError('/api/sensors');
            const sensorData = await sensorRes.json();
            if (sensorData.network_interfaces) {
                for (let iface of sensorData.network_interfaces) {
                    const ip = iface.ip;
                    const type = iface.type;
                    if (type === 'IPv4' && (ip.startsWith('127.') || ip.startsWith('169.254.'))) continue;
                    if (type === 'IPv6' && (ip === '::1' || ip.startsWith('fe80'))) continue;
                    addresses.push({ adapter: iface.name, type: type, ip: ip });
                }
            }
        }
    } catch(e) {
        console.error('获取IP地址失败', e);
    }

    let html = `<div class="sensor-left" style="width:100%;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div class="sensor-title">IP地址</div>
                        <button id="showIpconfigDetailBtn" class="small-btn" style="background: #8e44ad;">查看详细信息</button>
                    </div>
                    <div class="ip-item" style="margin-bottom: 6px;"><strong>公网出口</strong>: ${escapeHtml(publicIp)}</div>`;
    for (let addr of addresses) {
        html += `<div class="ip-item">${escapeHtml(addr.adapter)} (${addr.type}): ${escapeHtml(addr.ip)}</div>`;
    }
    if (addresses.length === 0) {
        html += `<div class="ip-item">未获取到有效本地IP地址</div>`;
    }
    html += `</div>`;
    container.innerHTML = html;

    const detailBtn = document.getElementById('showIpconfigDetailBtn');
    if (detailBtn) detailBtn.onclick = showIpconfigDetail;
}

async function showIpconfigDetail() {
    const modal = document.getElementById('ipconfigModal');
    const outputDiv = document.getElementById('ipconfigOutput');
    modal.style.display = 'flex';
    outputDiv.innerText = '加载中...';
    try {
        const res = await fetchWithError('/api/ipconfig_raw');
        const data = await res.json();
        if (data.success) {
            outputDiv.innerText = data.output;
        } else {
            outputDiv.innerText = '获取失败: ' + (data.error || '未知错误');
        }
    } catch(e) {
        outputDiv.innerText = '请求失败: ' + e.message;
    }
}

async function updateDisks() {
    const container = document.getElementById('disksGrid');
    if (!container) return;
    try {
        const res = await fetchWithError('/api/dashboard_stats');
        const data = await res.json();
        const disks = data.disks || [];
        if (disks.length === 0) {
            container.innerHTML = '<div class="disk-card">未获取到磁盘信息</div>';
            return;
        }
        let html = '<div class="disks-grid">';
        for (let disk of disks) {
            const percent = disk.percent || 0;
            let barColor = '#2ecc71';
            if (percent > 90) barColor = '#e74c3c';
            else if (percent > 70) barColor = '#f39c12';
            const usedGb = disk.used_gb || 0;
            const totalGb = disk.total_gb || 0;
            html += `
                <div class="disk-card">
                    <div class="disk-header">
                        <span class="disk-name">${escapeHtml(disk.mount)}</span>
                        <span class="disk-usage">${usedGb} GB / ${totalGb} GB (${percent}%)</span>
                    </div>
                    <div class="progress-bar-container">
                        <div class="progress-bar" style="width: ${percent}%; background-color: ${barColor};"></div>
                    </div>
                </div>
            `;
        }
        html += '</div>';
        container.innerHTML = html;
    } catch(e) {
        console.error('更新磁盘状态失败', e);
    }
}

async function refreshSensors() {
    const cpuRes = await fetchWithError('/api/dashboard_stats');
    const cpuData = await cpuRes.json();
    const sensorRes = await fetchWithError('/api/sensors');
    const sensorData = await sensorRes.json();

    let totalLoad = cpuData.total_load;
    let loadText = '';
    if (totalLoad < 30) loadText = '运行流畅';
    else if (totalLoad < 70) loadText = '负载中等';
    else loadText = '负载较高';
    document.getElementById('totalLoadDisplay').innerHTML = `总负载: ${totalLoad}% ${loadText}`;

    const sensorsGrid = document.getElementById('sensorsGrid');
    sensorsGrid.innerHTML = '';

    const cpuCard = document.createElement('div');
    cpuCard.className = 'sensor-card';
    cpuCard.innerHTML = `<div class="sensor-left"><div class="sensor-title">CPU</div><div class="sensor-value">${escapeHtml(cpuData.cpu.model || 'Unknown')}</div><div class="sensor-detail">核心: ${cpuData.cpu.physical_cores || '-'} 物理 / ${cpuData.cpu.logical_cores || '-'} 逻辑</div><div class="sensor-detail">占用: ${cpuData.cpu.percent || 0}%</div><div class="sensor-detail" id="cpuFreqDetail" style="${sensorData.cpu_freq ? '' : 'display:none'}">频率: ${sensorData.cpu_freq ? sensorData.cpu_freq.current + ' MHz' : ''}</div></div><div class="sensor-right"><canvas id="cpuGauge" width="100" height="100" class="small-gauge"></canvas></div>`;
    sensorsGrid.appendChild(cpuCard);
    drawSmallGauge('cpuGauge', cpuData.cpu.percent || 0);

    const memCard = document.createElement('div');
    memCard.className = 'sensor-card';
    memCard.innerHTML = `<div class="sensor-left"><div class="sensor-title">内存</div><div class="sensor-detail">总计: ${cpuData.memory.total_gb || 0} GB</div><div class="sensor-detail">已用: ${cpuData.memory.used_gb || 0} GB</div><div class="sensor-detail">占用: ${cpuData.memory.percent || 0}%</div></div><div class="sensor-right"><canvas id="memGauge" width="100" height="100" class="small-gauge"></canvas></div>`;
    sensorsGrid.appendChild(memCard);
    drawSmallGauge('memGauge', cpuData.memory.percent || 0);

    if (sensorData.temperatures) {
        const tempCard = document.createElement('div');
        tempCard.className = 'sensor-card';
        const tempPercent = Math.min(100, Math.max(0, (sensorData.temperatures.current / 90) * 100));
        tempCard.innerHTML = `<div class="sensor-left"><div class="sensor-title">温度</div><div class="sensor-value">${sensorData.temperatures.name}</div><div class="sensor-detail">当前: ${sensorData.temperatures.current} °C</div>${sensorData.temperatures.high ? `<div class="sensor-detail">警告阈值: ${sensorData.temperatures.high} °C</div>` : ''}</div><div class="sensor-right"><canvas id="tempGauge" width="100" height="100" class="small-gauge"></canvas></div>`;
        sensorsGrid.appendChild(tempCard);
        drawSmallGauge('tempGauge', tempPercent);
    }

    if (sensorData.battery) {
        const batteryCard = document.createElement('div');
        batteryCard.className = 'sensor-card';
        const percent = sensorData.battery.percent;
        let batteryColor = '#2ecc71';
        if (percent <= 20) batteryColor = '#e74c3c';
        else if (percent <= 50) batteryColor = '#f39c12';
        batteryCard.innerHTML = `<div class="sensor-left"><div class="sensor-title">电池</div><div class="sensor-value">${percent}%</div><div class="sensor-detail">${sensorData.battery.power_plugged ? '充电中' : '使用电池'}</div><div class="sensor-detail">剩余时间: ${sensorData.battery.time_str}</div></div><div class="sensor-right"><canvas id="batteryGauge" width="100" height="100" class="small-gauge"></canvas></div>`;
        sensorsGrid.appendChild(batteryCard);
        drawSmallGauge('batteryGauge', percent, batteryColor);
    }

    if (sensorData.fans) {
        const fanCard = document.createElement('div');
        fanCard.className = 'sensor-card';
        fanCard.innerHTML = `<div class="sensor-left"><div class="sensor-title">风扇</div><div class="sensor-value">${sensorData.fans.name}</div><div class="sensor-detail">转速: ${sensorData.fans.rpm} RPM</div></div>`;
        sensorsGrid.appendChild(fanCard);
    }

    if (sensorData.uptime || sensorData.process_count) {
        const sysCard = document.createElement('div');
        sysCard.className = 'sensor-card';
        sysCard.innerHTML = `<div class="sensor-left"><div class="sensor-title">系统</div>${sensorData.uptime ? `<div class="sensor-detail">运行时间: ${sensorData.uptime}</div>` : ''}${sensorData.process_count ? `<div class="sensor-detail">进程数: ${sensorData.process_count}</div>` : ''}</div>`;
        sensorsGrid.appendChild(sysCard);
    }

    // 加载风险预览
    loadRisksPreview();
}

async function loadRisksPreview() {
    const riskCardContainer = document.getElementById('riskCard');
    if (!riskCardContainer) return;
    try {
        const res = await fetchWithError('/api/risks');
        const data = await res.json();
        if (data.status === 'scanning') {
            riskCardContainer.innerHTML = `<div class="sensor-card" style="background:#fef9e3;">🔍 正在扫描风险...</div>`;
            return;
        }
        const risks = data.risks || [];
        if (risks.length > 0) {
            riskCardContainer.innerHTML = `<div class="sensor-card" style="background:#fff0f0; border-left: 4px solid #dc3545;">
                <div><strong>⚠️ 检测到 ${risks.length} 个风险</strong><br>
                <button class="small-btn" onclick="switchTab('risks')">查看详情</button></div>
            </div>`;
        } else {
            riskCardContainer.innerHTML = '';
        }
    } catch(e) {
        console.error('加载风险预览失败', e);
    }
}

async function initTrendChart() {
    const ctx = document.getElementById('trendChart').getContext('2d');
    trendChart = new Chart(ctx, {
        type: 'line',
        data: { datasets: [] },
        options: { responsive: true, maintainAspectRatio: true, scales: { y: { beginAtZero: true, title: { display: true, text: 'KB/s' } } } }
    });
    await fetchNetHistory();
    trendRefreshTimer = setInterval(() => {
        if (currentTrendMode === 'net') fetchNetHistory();
        else fetchDiskHistory();
    }, 2000);
}
async function fetchNetHistory() {
    const res = await fetchWithError('/api/net_io_history');
    const data = await res.json();
    netHistory = data.history || [];
    updateNetChart();
}
function updateNetChart() {
    if (!trendChart) return;
    const sent = netHistory.map(p => p[0]);
    const recv = netHistory.map(p => p[1]);
    const labels = netHistory.map((_, i) => i);
    trendChart.data = { labels, datasets: [{ label: '上行 KB/s', data: sent, borderColor: '#3a6ea5', fill: false }, { label: '下行 KB/s', data: recv, borderColor: '#e67e22', fill: false }] };
    trendChart.update();
}
async function fetchDiskHistory() {
    const res = await fetchWithError('/api/disk_io');
    const data = await res.json();
    diskIoHistory = data;
    const disks = Object.keys(diskIoHistory);
    if (disks.length === 0) return;
    if (!currentDisk || !disks.includes(currentDisk)) currentDisk = disks[0];
    const select = document.getElementById('diskSelectDropdown');
    select.innerHTML = '';
    disks.forEach(d => { const opt = document.createElement('option'); opt.value = d; opt.textContent = d; if (d === currentDisk) opt.selected = true; select.appendChild(opt); });
    select.onchange = () => { currentDisk = select.value; updateDiskChart(); };
    updateDiskChart();
}
function updateDiskChart() {
    if (!trendChart || !currentDisk) return;
    const history = diskIoHistory[currentDisk] || [];
    const readRates = history.map(p => p[0]);
    const writeRates = history.map(p => p[1]);
    const labels = history.map((_, i) => i);
    trendChart.data = { labels, datasets: [{ label: '读 KB/s', data: readRates, borderColor: '#2ecc71', fill: false }, { label: '写 KB/s', data: writeRates, borderColor: '#e74c3c', fill: false }] };
    trendChart.update();
}

async function refreshServices() {
    const res = await fetchWithError('/api/services');
    const services = await res.json();
    const grid = document.getElementById('servicesGrid');
    grid.innerHTML = '';
    const newStates = {};
    for(let svc of services) {
        newStates[svc.id] = svc.running;
        let statusClass = 'status-stopped';
        let statusText = '';
        switch(svc.health) {
            case 'running': statusClass = 'status-running'; statusText = `运行中 (PID: ${svc.pid||'?'})`; break;
            case 'crashed': statusClass = 'status-crashed'; statusText = '崩溃'; break;
            case 'start_failed': statusClass = 'status-start-failed'; statusText = '启动失败'; break;
            case 'maintenance': statusClass = 'status-maintenance'; statusText = '维护中'; break;
            default: statusClass = 'status-stopped'; statusText = '已停止';
        }
        const maintBtnText = svc.maintenance ? '取消维护' : '停机维护';
        const card = document.createElement('div');
        card.className = 'service-card';
        card.dataset.id = svc.id;
        card.innerHTML = `<div class="card-header"><span class="service-name">${escapeHtml(svc.name)}</span><span class="status-badge ${statusClass}">${statusText}</span></div><div class="info-row"><span class="info-label">ID</span><span class="info-value">${escapeHtml(svc.id)}</span></div><div class="info-row"><span class="info-label">端口</span><span class="info-value">${svc.port||'未配置'}</span></div><div class="card-actions"><button class="btn btn-start" data-id="${svc.id}">启动</button><button class="btn btn-stop" data-id="${svc.id}">停止</button><button class="btn btn-restart" data-id="${svc.id}">重启</button><button class="btn btn-logs" data-id="${svc.id}">日志</button><button class="btn btn-maintenance" data-id="${svc.id}" data-maint="${svc.maintenance}">${maintBtnText}</button></div>`;
        grid.appendChild(card);
    }
    const now = Date.now();
    for(let id in lastServiceStates){
        if(lastServiceStates[id]===true && newStates[id]===false){
            const svc = services.find(s=>s.id===id);
            if(!svc) continue;
            const lastAction = svc.last_action;
            const isPending = pendingStopIds.has(id);
            const stopTime = stopTimestamps.get(id);
            const isRecentSelf = stopTime && (now-stopTime)<5000;
            let isOther=false, otherIp=null;
            if(lastAction && lastAction.action==='stop' && (now - lastAction.timestamp*1000)<300000){
                if(lastAction.source_ip !== currentDeviceIp){
                    isOther=true;
                    otherIp=lastAction.source_ip;
                }
            }
            if(isOther) showAlertModal(`其他设备 (${otherIp}) 停止了服务“${svc.name}”`);
            else if(!isPending && !isRecentSelf && svc.health !== 'maintenance' && svc.health !== 'stopped') showAlertModal(`服务意外停止: ${svc.name}\n请检查日志或手动重启。`);
        }
    }
    for(let id of pendingStopIds) if(newStates[id]===false){ pendingStopIds.delete(id); stopTimestamps.delete(id); }
    lastServiceStates = newStates;
    attachServiceEvents();
}
function attachServiceEvents() {
    document.querySelectorAll('.btn-start').forEach(btn => btn.onclick = () => actionHandler(btn.dataset.id, 'start'));
    document.querySelectorAll('.btn-stop').forEach(btn => btn.onclick = () => actionHandler(btn.dataset.id, 'stop'));
    document.querySelectorAll('.btn-restart').forEach(btn => btn.onclick = () => actionHandler(btn.dataset.id, 'restart'));
    document.querySelectorAll('.btn-logs').forEach(btn => btn.onclick = () => showLogs(btn.dataset.id));
    document.querySelectorAll('.btn-maintenance').forEach(btn => btn.onclick = async () => {
        const id = btn.dataset.id;
        const currently = btn.dataset.maint === 'true';
        const res = await fetchWithError(`/api/services/${id}/maintenance`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled: !currently}) });
        const data = await res.json();
        if (data.success) { showToast(data.message, 'success'); setTimeout(() => { refreshServices(); refreshMonitor(); }, 600); }
        else showAlertModal(data.message);
    });
}
async function actionHandler(id, action){
    let url = `/api/services/${id}/${action}`;
    if(action==='stop'||action==='restart'){ pendingStopIds.add(id); stopTimestamps.set(id,Date.now()); }
    try{
        const res = await fetchWithError(url,{method:'POST'});
        const data = await res.json();
        if(data.success) { showToast(`✅ ${data.message}`,'success'); setTimeout(() => { refreshServices(); refreshMonitor(); }, 600); }
        else { showAlertModal(`操作失败：\n${data.message}`); if(action==='stop'||action==='restart'){ pendingStopIds.delete(id); stopTimestamps.delete(id); } }
    } catch(err){ showAlertModal(`网络错误：${err.message}`); if(action==='stop'||action==='restart'){ pendingStopIds.delete(id); stopTimestamps.delete(id); } }
}
async function showLogs(id){
    currentLogServiceId = id;
    const modal = document.getElementById('logModal');
    const logContent = document.getElementById('logContent');
    const logTitle = document.getElementById('logTitle');
    const res = await fetchWithError('/api/services');
    const services = await res.json();
    const svc = services.find(s=>s.id===id);
    logTitle.innerText = `${svc?.name||id} 日志 (最后15行)`;
    modal.style.display = 'flex';
    await refreshLogContent();
    document.getElementById('clearLogBtn').onclick = () => {
        showConfirmModal('确定要清空此服务的日志文件吗？', async () => {
            const clearRes = await fetchWithError(`/api/services/${id}/clear_log`, { method: 'POST' });
            const clearData = await clearRes.json();
            if (clearData.success) { showToast('日志已清空', 'success'); await refreshLogContent(); }
            else showAlertModal('清空失败: ' + clearData.message);
        });
    };
}
async function refreshLogContent() {
    if (!currentLogServiceId) return;
    const logContent = document.getElementById('logContent');
    logContent.innerText = "加载中...";
    try {
        const response = await fetchWithError(`/api/services/${currentLogServiceId}/logs?lines=80`);
        const data = await response.json();
        if (!response.ok || data.error) {
            console.error("日志加载错误:", data.error || `HTTP ${response.status}`);
            logContent.innerText = `❌ 读取失败: ${data.error || '未知错误'}\n\n请检查：\n- 日志文件是否存在\n- 文件权限是否可读\n- 是否被其他程序独占`;
        } else {
            logContent.innerText = data.logs || "(无日志内容)";
        }
        setTimeout(scrollLogToBottom, 100);
    } catch (e) {
        console.error("请求日志异常:", e);
        logContent.innerText = `❌ 网络请求失败: ${e.message}\n请检查面板服务是否正常运行。`;
    }
}
async function startAll(){
    const res = await fetchWithError('/api/start_all',{method:'POST'});
    const results = await res.json();
    for(let r of results){ if(r.success) showToast(`${r.name} 启动成功`,'success'); else showAlertModal(`${r.name} 启动失败:\n${r.message}`); }
    setTimeout(() => { refreshServices(); refreshMonitor(); }, 600);
}
async function stopAll(){
    const listRes = await fetchWithError('/api/services');
    const services = await listRes.json();
    const now=Date.now();
    for(let svc of services){ pendingStopIds.add(svc.id); stopTimestamps.set(svc.id,now); }
    const stopRes = await fetchWithError('/api/stop_all',{method:'POST'});
    const results = await stopRes.json();
    for(let r of results){ if(r.success) showToast(`${r.name} 已停止`,'success'); else showToast(`${r.name} 停止失败`,'error'); }
    setTimeout(() => { refreshServices(); refreshMonitor(); }, 600);
}

async function refreshTrafficCards() {
    const res = await fetchWithError('/api/services');
    const services = await res.json();
    const grid = document.getElementById('trafficGrid');
    grid.innerHTML = '';
    for(let svc of services){
        const card = document.createElement('div');
        card.className = 'traffic-card';
        card.innerHTML = `<div class="traffic-card-header"><span class="traffic-name">${escapeHtml(svc.name)}</span><span class="traffic-current" id="traffic-current-${svc.id}">加载中...</span></div><canvas id="traffic-canvas-${svc.id}" class="traffic-canvas" width="400" height="80" style="width:100%; height:80px;"></canvas>`;
        grid.appendChild(card);
    }
    await updateAllTraffic();
}
async function updateAllTraffic(){
    const res = await fetchWithError('/api/services');
    const services = await res.json();
    for(let svc of services){
        try{
            const trafficRes = await fetchWithError(`/api/traffic/${svc.id}`);
            const data = await trafficRes.json();
            const canvas = document.getElementById(`traffic-canvas-${svc.id}`);
            if(canvas && data.values){
                drawWave(canvas, data.values);
                const cur = data.values[data.values.length-1]||0;
                const span = document.getElementById(`traffic-current-${svc.id}`);
                if(span) span.innerText = `最近5秒: ${cur} 请求`;
            }
        }catch(e){}
    }
}
function drawWave(canvas, values) {
    if (!canvas || !values.length) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = w; canvas.height = h;
    ctx.clearRect(0, 0, w, h);
    if(values.length < 2) return;
    const maxVal = Math.max(...values, 1);
    const step = w/(values.length-1);
    ctx.beginPath();
    ctx.strokeStyle='rgba(0,0,0,0.1)';
    ctx.lineWidth=0.5;
    for(let i=0;i<=4;i++){ let y = h-(i/4)*h; ctx.moveTo(0,y); ctx.lineTo(w,y); ctx.stroke(); }
    ctx.beginPath();
    let first=true;
    for(let i=0;i<values.length;i++){
        let x=i*step, y=h-(values[i]/maxVal)*h;
        if(first){ ctx.moveTo(x,y); first=false; }
        else{ let prevX=(i-1)*step, prevY=h-(values[i-1]/maxVal)*h; let cpX=(prevX+x)/2, cpY=prevY; ctx.quadraticCurveTo(cpX,cpY,x,y); }
    }
    ctx.strokeStyle='#3a6ea5';
    ctx.lineWidth=2;
    ctx.stroke();
    ctx.lineTo(w,h); ctx.lineTo(0,h); ctx.closePath();
    let grad=ctx.createLinearGradient(0,0,0,h);
    grad.addColorStop(0,'rgba(58,110,165,0.3)');
    grad.addColorStop(1,'rgba(58,110,165,0.05)');
    ctx.fillStyle=grad;
    ctx.fill();
}

async function refreshMonitor() {
    const monitorTab = document.getElementById('monitor-tab');
    if (monitorTab.style.display !== 'block') return;
    const res = await fetchWithError('/api/services_resources');
    const data = await res.json();
    let html = '<table style="width:100%; border-collapse:collapse;"><thead><tr><th>服务名称</th><th>状态</th><th>CPU%</th><th>内存(MB)</th></tr></thead><tbody>';
    for(let s of data) {
        let statusIcon = '';
        let statusText = '';
        switch(s.health) {
            case 'running': statusIcon = '🟢'; statusText = '运行中'; break;
            case 'crashed': statusIcon = '🔴'; statusText = '崩溃'; break;
            case 'start_failed': statusIcon = '🟡'; statusText = '启动失败'; break;
            case 'maintenance': statusIcon = '⚪'; statusText = '维护中'; break;
            default: statusIcon = '⚫'; statusText = '已停止';
        }
        html += `<tr><td>${escapeHtml(s.name)}</td><td>${statusIcon} ${statusText}</td><td>${s.running ? s.cpu_percent : '-'}</td><td>${s.running ? s.mem_mb : '-'}</td></tr>`;
    }
    html += '</tbody></table>';
    document.getElementById('monitorTable').innerHTML = html;
}

async function loadSettings() {
    const res = await fetchWithError('/api/settings');
    const settings = await res.json();
    document.getElementById('panelHost').value = settings.panel_host;
    document.getElementById('panelPort').value = settings.panel_port;
}
async function saveSettings() {
    const host = document.getElementById('panelHost').value;
    const port = parseInt(document.getElementById('panelPort').value);
    const res = await fetchWithError('/api/settings', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({panel_host: host, panel_port: port}) });
    const data = await res.json();
    if (data.success) showAlertModal('配置已保存，请手动重启面板服务以使新端口生效。');
    else showAlertModal('保存失败');
}

async function loadServiceConfigs() {
    const res = await fetchWithError('/api/service_configs');
    const services = await res.json();
    const container = document.getElementById('serviceConfigList');
    container.innerHTML = '';
    if (services.length === 0) { container.innerHTML = '<p>暂无服务配置，点击“添加服务”创建。</p>'; return; }
    const table = document.createElement('table');
    table.style.width = '100%';
    table.style.borderCollapse = 'collapse';
    table.innerHTML = '<thead><tr><th>ID</th><th>名称</th><th>命令</th><th>工作目录</th><th>端口</th><th>操作</th></tr></thead><tbody></tbody>';
    const tbody = table.querySelector('tbody');
    for (let svc of services) {
        const row = tbody.insertRow();
        row.insertCell(0).innerText = svc.id;
        row.insertCell(1).innerText = svc.name;
        row.insertCell(2).innerText = typeof svc.command === 'string' ? svc.command : JSON.stringify(svc.command);
        row.insertCell(3).innerText = svc.cwd || '.';
        row.insertCell(4).innerText = svc.port || '-';
        const actionCell = row.insertCell(5);
        const editBtn = document.createElement('button'); editBtn.innerText = '编辑'; editBtn.className = 'small-btn'; editBtn.style.marginRight = '0.5rem'; editBtn.onclick = () => openServiceModal(svc);
        const delBtn = document.createElement('button'); delBtn.innerText = '删除'; delBtn.className = 'small-btn'; delBtn.style.background = '#c0392b'; delBtn.onclick = () => deleteService(svc.id);
        actionCell.appendChild(editBtn); actionCell.appendChild(delBtn);
    }
    container.appendChild(table);
}
function openServiceModal(service = null) {
    const modal = document.getElementById('serviceModal');
    document.getElementById('serviceModalTitle').innerText = service ? '编辑服务' : '添加服务';
    document.getElementById('editServiceId').value = service ? service.id : '';
    document.getElementById('serviceId').value = service ? service.id : '';
    document.getElementById('serviceName').value = service ? service.name : '';
    const cmd = service ? (typeof service.command === 'string' ? service.command : JSON.stringify(service.command)) : '';
    document.getElementById('serviceCommand').value = cmd;
    document.getElementById('serviceCwd').value = service ? (service.cwd || '') : '';
    document.getElementById('servicePort').value = service ? (service.port || '') : '';
    modal.style.display = 'flex';
}
function closeServiceModal() { document.getElementById('serviceModal').style.display = 'none'; }
async function saveService() {
    const id = document.getElementById('serviceId').value.trim();
    const name = document.getElementById('serviceName').value.trim();
    let command = document.getElementById('serviceCommand').value.trim();
    const cwd = document.getElementById('serviceCwd').value.trim() || '.';
    const port = document.getElementById('servicePort').value.trim();
    if (!id || !name || !command) { showAlertModal('请填写 ID、名称和启动命令'); return; }
    let commandParsed;
    try { if (command.startsWith('[') && command.endsWith(']')) { commandParsed = JSON.parse(command); } else { commandParsed = command; } } catch(e) { commandParsed = command; }
    const editId = document.getElementById('editServiceId').value;
    const method = editId ? 'PUT' : 'POST';
    const url = editId ? `/api/service_configs/${editId}` : '/api/service_configs';
    const body = { id, name, command: commandParsed, cwd, port: port ? parseInt(port) : null };
    const res = await fetchWithError(url, { method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
    const data = await res.json();
    if (data.success) { showToast(data.message, 'success'); closeServiceModal(); loadServiceConfigs(); refreshServices(); }
    else showAlertModal(data.message);
}
async function deleteService(id) {
    showConfirmModal(`确定要删除服务 ${id} 吗？该操作会停止服务并删除配置。`, async () => {
        const res = await fetchWithError(`/api/service_configs/${id}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.success) { showToast(data.message, 'success'); loadServiceConfigs(); refreshServices(); }
        else showAlertModal(data.message);
    });
}

// ---------- 风险检测 ----------
async function loadRisks() {
    const container = document.getElementById('risksList');
    if (!container) return;
    try {
        const res = await fetchWithError('/api/risks');
        const data = await res.json();
        if (data.status === 'scanning') {
            container.innerHTML = '<div class="sensor-card" style="background:#fef9e3;">🔍 正在扫描系统风险，请稍候...</div>';
            return;
        }
        const risks = data.risks || [];
        if (risks.length === 0) {
            container.innerHTML = '<div class="sensor-card" style="background:#d4edda;">✅ 未检测到任何风险，系统状态良好。</div>';
            return;
        }
        let html = '';
        for (let r of risks) {
            html += `<div class="sensor-card" style="margin-bottom:1rem; border-left: 5px solid ${r.severity==='high'?'#dc3545':'#ffc107'};">
                <div><strong>${escapeHtml(r.type)}</strong> (${r.severity})<br>${escapeHtml(r.detail)}<br>
                <button class="small-btn" onclick="showSolution('${escapeHtml(r.solution)}')">查看解决方法</button></div>
            </div>`;
        }
        container.innerHTML = html;
    } catch(e) {
        container.innerHTML = '<div class="sensor-card" style="background:#f8d7da;">❌ 加载风险失败，请检查面板日志。</div>';
    }
}

function showSolution(solution) {
    showAlertModal(`解决方法：\n${solution}`);
}

// ---------- 定时器与初始化 ----------
function startTimers() {
    if (serviceRefreshTimer) clearInterval(serviceRefreshTimer);
    if (monitorRefreshTimer) clearInterval(monitorRefreshTimer);
    if (trafficRefreshTimer) clearInterval(trafficRefreshTimer);
    if (sensorsRefreshTimer) clearInterval(sensorsRefreshTimer);
    serviceRefreshTimer = setInterval(() => { if (document.querySelector('.nav-item.active').dataset.tab === 'services') refreshServices(); }, 5000);
    monitorRefreshTimer = setInterval(refreshMonitor, 3000);
    trafficRefreshTimer = setInterval(() => { if (document.querySelector('.nav-item.active').dataset.tab === 'traffic') updateAllTraffic(); }, 5000);
    sensorsRefreshTimer = setInterval(() => {
        if (document.querySelector('.nav-item.active').dataset.tab === 'dashboard') {
            refreshSensors();
            updateNetworkCard();
            updateIpCard();
            updateDisks();
        }
    }, 1000);
}

async function init() {
    await fetchMyIp();
    startTimers();
    await refreshSensors();
    await updateNetworkCard();
    await updateIpCard();
    await updateDisks();
    await refreshServices();
    await refreshTrafficCards();
    await loadSettings();
    await loadServiceConfigs();
    await initTrendChart();
    await loadDeploymentConfig();
    document.getElementById('startAllBtn').onclick = startAll;
    document.getElementById('stopAllBtn').onclick = stopAll;
    document.getElementById('saveSettingsBtn').onclick = saveSettings;
    document.getElementById('addServiceBtn').onclick = () => openServiceModal();
    document.getElementById('saveServiceBtn').onclick = saveService;
    document.getElementById('saveDeployConfigBtn').onclick = saveDeploymentConfig;
    document.getElementById('switchToNetBtn').onclick = () => { currentTrendMode = 'net'; document.getElementById('switchToNetBtn').classList.add('active'); document.getElementById('switchToDiskBtn').classList.remove('active'); document.getElementById('diskSelect').style.display = 'none'; fetchNetHistory(); };
    document.getElementById('switchToDiskBtn').onclick = () => { currentTrendMode = 'disk'; document.getElementById('switchToDiskBtn').classList.add('active'); document.getElementById('switchToNetBtn').classList.remove('active'); document.getElementById('diskSelect').style.display = 'block'; fetchDiskHistory(); };
    document.querySelectorAll('.nav-item').forEach(item => { item.addEventListener('click', () => switchTab(item.dataset.tab)); });
    window.onclick = function(e){
        if(e.target === document.getElementById('logModal')) closeModal();
        if(e.target === document.getElementById('alertModal')) closeAlertModal();
        if(e.target === document.getElementById('serviceModal')) closeServiceModal();
        if(e.target === document.getElementById('ipconfigModal')) closeIpconfigModal();
    };
}
init();