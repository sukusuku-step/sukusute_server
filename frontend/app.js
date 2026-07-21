// APIベースURL設定
const API_BASE = 'http://192.168.11.2:8000';

// 目標歩数
const GOAL = 3000;

// 状態管理
let state = {
    children: [],           // 児童一覧（名前、ID）
    selectedChildId: null,  // 選択した児童ID
    selectedDate: new Date(), // 選択した日付
    todayStats: null,       // 今日の集計情報
    studentSteps: {},       // 最新の歩数
    studentDistances: {},   // 最新の距離
    sortMode: 'steps'       // ソートモード
};

// ===== API通信 =====

async function apiGet(url) {
    try {
        const response = await fetch(`${API_BASE}${url}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error('API error:', error);
        return null;
    }
}

// ===== 初期化 =====

async function init() {
    // 日付セレクターを設定
    document.getElementById('dateSelector').value = formatDate(new Date());
    state.selectedDate = new Date();

    // ソートモードのイベントリスナーを追加
    document.getElementById('sortOrder').addEventListener('change', (e) => {
        state.sortMode = e.target.value;
        renderStudentGrid();
    });

    // データ読み込み（児童一覧を先に取得）
    await loadChildren();
    console.log('init: 初期化後、児童数', state.children.length);
    await loadTodayStats();

    // 最初に選択
    if (state.children.length > 0) {
        selectChild(state.children[0].child_id);
    }

    updateLastUpdateTime();
    // 5秒ごとにデータを更新（再帰的setTimeoutで確実に更新）
    setTimeout(refreshData, 5000);
}

// ===== 児童データ =====

async function loadChildren() {
    console.log('loadChildren: 児童一覧を取得開始...');
    try {
        const result = await apiGet('/api/children');
        console.log('loadChildren: API応答:', result);

        if (result && result.status === 'ok' && result.children) {
            const newChildren = result.children;
            const oldCount = state.children.length;

            console.log('loadChildren: oldCount=' + oldCount + ', newCount=' + newChildren.length);
            console.log('loadChildren: oldIds=', state.children.map(c => c.child_id));
            console.log('loadChildren: newIds=', newChildren.map(c => c.child_id));

            // 常に児童データを更新
            state.children = newChildren;
            console.log('loadChildren: updated, total=' + state.children.length);

            // 常にグリッドを再描画
            console.log('loadChildren: calling renderStudentGrid...');
            renderStudentGrid();
            console.log('loadChildren: renderStudentGrid done');
        } else {
            console.error('loadChildren: invalid response:', result);
        }
    } catch (error) {
        console.error('loadChildren: exception:', error);
    }
}

// 児童グリッドを強制的に再描画
function forceRefreshStudentGrid() {
    console.log('forceRefreshStudentGrid: 呼び出し', state.children.length, '人の児童');
    renderStudentGrid();
}

// ===== 集計データ =====

async function loadTodayStats() {
    try {
        console.log('loadTodayStats: 開始');
        const date = state.selectedDate;
        const url = `/api/stats/today?year=${date.getFullYear()}&month=${date.getMonth() + 1}&day=${date.getDate()}`;
        console.log('loadTodayStats: URL', url);

        const result = await apiGet(url);
        console.log('loadTodayStats: 応答', result);

        if (result?.status === 'ok') {
            state.todayStats = result;
            updateStats(result);

            // 歩数状態更新 - 常に更新
            if (result.student_ranking && Array.isArray(result.student_ranking)) {
                console.log('loadTodayStats: 生徒ランキング', result.student_ranking);
                // 既存の歩数データをクリア
                state.studentSteps = {};
                // 新しい歩数データを更新
                result.student_ranking.forEach(s => {
                    state.studentSteps[s.child_id] = s.steps;
                });
                console.log('loadTodayStats: 更新後の歩数データ', state.studentSteps);
            }

            // 常にグリッドを再描画
            renderStudentGrid();
            renderRanking(result);
            renderWarnings(result);
            renderDataLog(result);
        } else {
            console.error('loadTodayStats: エラー', result);
        }
    } catch (error) {
        console.error('loadTodayStats: 例外', error);
        throw error;
    }
}

// 統計情報を更新
async function updateStats(stats) {
    document.getElementById('totalSteps').textContent =
        stats.total_steps > 0 ? stats.total_steps.toLocaleString() : '-';
    document.getElementById('avgSteps').textContent =
        stats.avg_steps > 0 ? stats.avg_steps.toLocaleString() : '-';
    document.getElementById('goalMetCount').innerHTML =
        `${stats.goal_met_count}<span class="unit">人</span>`;
    document.getElementById('goalMetPercent').textContent =
        `/${stats.total_students}人`;
    document.getElementById('totalStudents').textContent = stats.total_students;

    // 前日比
    if (stats.step_change !== undefined && stats.step_change !== 0) {
        const sign = stats.step_change >= 0 ? '+' : '';
        document.getElementById('stepChangeSub').textContent =
            `前日比 ${sign}${stats.step_change}`;
    }

    // 交流回数を取得
    await updateMeetingCount();
}

// 交流回数を更新
async function updateMeetingCount() {
    const date = state.selectedDate;
    const result = await apiGet(
        `/api/stats/distance-today?year=${date.getFullYear()}&month=${date.getMonth() + 1}&day=${date.getDate()}`
    );

    if (result?.status === 'ok') {
        document.getElementById('meetingCount').textContent =
            result.meeting_count > 0 ? result.meeting_count : '-';

        // 距離ランキング更新
        renderDistanceRanking(result);
    }
}

// ===== 児童グリッド描画 =====

function renderStudentGrid() {
    const grid = document.getElementById('studentGrid');

    if (state.children.length === 0) {
        grid.innerHTML = '<div class="loading">児童データがありません</div>';
        return;
    }

    // ソート
    let sorted = [...state.children];
    switch (state.sortMode) {
        case 'steps':
            sorted.sort((a, b) =>
                (state.studentSteps[b.child_id] || 0) -
                (state.studentSteps[a.child_id] || 0)
            );
            break;
        case 'name':
            // 名前が存在する場合は名前順、なければID順
            sorted.sort((a, b) => {
                if (a.name && b.name) return a.name.localeCompare(b.name);
                return a.child_id - b.child_id;
            });
            break;
        case 'rank':
            sorted.sort((a, b) => a.child_id - b.child_id);
            break;
    }

    grid.innerHTML = sorted.map((child, index) => {
        const steps = state.studentSteps[child.child_id] || 0;
        const distance = state.studentDistances[child.child_id] || 0;
        const percent = Math.min((steps / GOAL) * 100, 100);
        const isActive = child.child_id === state.selectedChildId;
        let barClass = 'low';
        if (percent >= 100) barClass = 'complete';
        else if (percent >= 70) barClass = 'high';
        else if (percent >= 40) barClass = 'medium';

        return `
            <div class="student-card ${isActive ? 'active' : ''}" onclick="selectChild(${child.child_id})">
                <div class="student-card-header">
                    <span class="student-name">ID: ${child.child_id}</span>
                    <span class="student-rank">${index + 1}位</span>
                </div>
                <div class="student-steps">${steps > 0 ? steps.toLocaleString() : '-'} 歩</div>
                <div class="student-goal">${percent.toFixed(0)}% 達成</div>
                <div class="goal-bar">
                    <div class="goal-bar-fill ${barClass}" style="width: ${percent}%"></div>
                </div>
                <div class="student-meta">
                    <span>目標: ${GOAL.toLocaleString()}歩</span>
                    <span>${steps >= GOAL ? '✓ 達成' : `残り ${Math.max(0, GOAL - steps).toLocaleString()}歩`}</span>
                </div>
                <div class="device-info">
                    ID: ${child.child_id} | Device: <code>${child.device_id.toString().substring(0, 8)}...</code>
                </div>
            </div>
        `;
    }).join('');
}

// ===== 児童選択・モーダル =====

async function selectChild(childId, skipModal = false) {
    // 既に選択されている場合は解除
    if (state.selectedChildId === childId) {
        state.selectedChildId = null;
        closeModal();
        renderStudentGrid();
        return;
    }

    state.selectedChildId = childId;
    const child = state.children.find(c => c.child_id === childId);
    if (!child) return;

    // 歩数データを取得
    const date = state.selectedDate;
    const result = await apiGet(
        `/api/children/${childId}/steps?year=${date.getFullYear()}&month=${date.getMonth() + 1}&day=${date.getDate()}`
    );

    if (result?.status === 'ok') {
        state.studentSteps[childId] = result.steps;
        renderStudentGrid();
        // 自動更新時はモーダルを表示しない
        if (!skipModal) {
            showChildModal(child, result);
        }
    }
}

// モーダルを表示
function showChildModal(child, stepData) {
    const modal = document.getElementById('modalOverlay');
    const title = document.getElementById('modalTitle');
    const content = document.getElementById('modalContent');

    title.textContent = `ID: ${child.child_id} - 歩数詳細`;

    // 時間別チャートを作成
    const maxHourly = Math.max(...stepData.steps_by_hour.map(d => d.steps), 1);
    const hourlyChart = stepData.steps_by_hour.map(d => {
        const height = (d.steps / maxHourly) * 160;
        let cls = 'low';
        if (d.steps > 500) cls = 'medium';
        if (d.steps > 1000) cls = 'high';
        return `
            <div class="hourly-bar-item">
                <span class="hourly-value">${d.steps > 0 ? d.steps : ''}</span>
                <div class="hourly-bar ${cls}" style="height: ${Math.max(height, 2)}px"></div>
                <span class="hourly-label">${d.hour}時</span>
            </div>
        `;
    }).join('');

    // 履歴チャート（過去7日）を作成
    let historyChart = '';
    if (stepData.history && stepData.history.length > 0) {
        const maxSteps = Math.max(...stepData.history.map(h => h.steps), 1);
        const historyItems = stepData.history.map((d, i) => {
            const height = (d.steps / maxSteps) * 120;
            const dateStr = d.date ? `${d.date.getMonth()+1}/${d.date.getDate()}` : `D${i+1}`;
            const barClass = d.steps >= GOAL ? 'high' : 'medium';
            const bgColor = d.steps >= GOAL
                ? 'linear-gradient(180deg, #64ffda, #00ff88)'
                : 'linear-gradient(180deg, #749aff, #4285f4)';
            return `
                <div class="history-bar-item">
                    <span class="history-value">${d.steps.toLocaleString()}</span>
                    <div class="history-bar ${barClass}" style="height: ${Math.max(height, 2)}px; background: ${bgColor}"></div>
                    <span class="history-label">${dateStr}</span>
                </div>
            `;
        }).join('');
        historyChart = `
            <h3 style="color: #fff; font-size: 14px; margin: 16px 0 12px;">過去7日間</h3>
            <div class="history-chart">${historyItems}</div>
        `;
    }

    content.innerHTML = `
        <div style="margin-bottom: 16px;">
            <div style="font-size: 32px; font-weight: 700; color: #64ffda; margin-bottom: 8px;">
                ${stepData.steps.toLocaleString()} 歩
            </div>
            <div style="font-size: 13px; color: #8898aa;">
                達成率: ${Math.min((stepData.steps / GOAL) * 100, 100).toFixed(1)}% |
                歩行時間: ${stepData.walk_time}分 |
                カロリ: ${stepData.calories}kcal
                ${stepData.goal_met ? ' | ✓ 達成!' : ''}
            </div>
            <div class="device-info" style="margin-top: 12px;">
                デバイスID: <code>${child.device_id.toString()}</code>
            </div>
        </div>

        <h3 style="color: #fff; font-size: 14px; margin-bottom: 12px;">時間別歩数</h3>
        <div class="hourly-chart">${hourlyChart}</div>

        ${historyChart}
    `;

    modal.classList.add('active');
}

// モーダルを閉じる
function closeModal() {
    document.getElementById('modalOverlay').classList.remove('active');
}

// モーダル外クリックで閉じる
document.getElementById('modalOverlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
});

// ===== ランキング描画 =====

function renderRanking(stats) {
    const container = document.getElementById('rankingList');
    if (!stats?.student_ranking) {
        container.innerHTML = '<div style="color: #8898aa; font-size: 12px;">データなし</div>';
        return;
    }

    const top10 = [...stats.student_ranking]
        .sort((a, b) => b.steps - a.steps)
        .slice(0, 10);

    container.innerHTML = `
        <div style="font-size: 12px; color: #8898aa; margin-bottom: 8px;">🏃 歩数ランキング</div>
        ${top10.map((s, i) => `
            <div class="ranking-item">
                <span class="ranking-name">${i + 1}. ID: ${s.child_id}</span>
                <span class="ranking-steps">${s.steps.toLocaleString()} 歩</span>
            </div>
        `).join('')}
    `;
}

// 距離ランキングを描画
function renderDistanceRanking(stats) {
    // トップペアを描画
    if (stats?.top_pairs && stats.top_pairs.length > 0) {
        const topPairsContainer = document.getElementById('topPairsList');
        if (topPairsContainer) {
            const topPairs = stats.top_pairs.slice(0, 5);
            topPairsContainer.innerHTML = topPairs.map((p, i) => `
                <div class="ranking-item">
                    <span class="ranking-name">${i + 1}. ID: ${p.child_id_1} ↔ ID: ${p.child_id_2}</span>
                    <span class="ranking-steps">${(p.distance * 1000).toFixed(0)} m</span>
                </div>
            `).join('');
        }
    }
}

// ===== 警告・ログ描画 =====

function renderWarnings(stats) {
    const container = document.getElementById('warningsList');
    if (!stats?.warnings || stats.warnings.length === 0) {
        container.innerHTML = '<div style="color: #8898aa; font-size: 12px;">異常なし</div>';
        return;
    }

    container.innerHTML = stats.warnings.map(w => `
        <div class="warning-item">
            <span class="warning-name">ID: ${w.child_id}</span>: 普段の${w.percent}%しか歩いていません
        </div>
    `).join('');
}

// データログを描画
function renderDataLog(stats) {
    const container = document.getElementById('dataLog');
    if (!stats?.student_ranking || stats.student_ranking.length === 0) {
        container.innerHTML = '<div style="color: #8898aa; font-size: 12px;">データ受信待ち...</div>';
        return;
    }

    const now = new Date();
    const top5 = [...stats.student_ranking]
        .sort((a, b) => b.steps - a.steps)
        .slice(0, 5);

    container.innerHTML = top5.map((s, i) => {
        const time = new Date(now.getTime() - i * 60000);
        const timeStr = `${String(time.getHours()).padStart(2, '0')}:${String(time.getMinutes()).padStart(2, '0')}`;
        return `
            <div class="ranking-item">
                <span style="color: #8898aa; font-size: 11px;">${timeStr}</span>
                <span style="color: #64ffda; font-size: 12px;">ID: ${s.child_id}: ${s.steps.toLocaleString()}歩</span>
            </div>
        `;
    }).join('');
}

// ===== 日付変更 =====

async function onDateChange() {
    const value = document.getElementById('dateSelector').value;
    if (value) {
        state.selectedDate = new Date(value);
        await loadTodayStats();
        if (state.selectedChildId) {
            selectChild(state.selectedChildId);
        }
    }
}

document.getElementById('dateSelector').addEventListener('change', onDateChange);

// ===== ユーティリティ =====

// 更新時間を更新
function updateLastUpdateTime() {
    const now = new Date();
    document.getElementById('lastUpdate').textContent =
        `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
}

// データを更新
async function refreshData() {
    try {
        updateLastUpdateTime();
        await loadTodayStats();
        // 自動更新時はモーダルを表示しない（skipModal=true）
        if (state.selectedChildId) {
            await selectChild(state.selectedChildId, true);
        }
    } catch (error) {
        console.error('データ更新エラー:', error);
    } finally {
        // 次の更新をスケジュール（前のリクエストが完了した後）
        setTimeout(refreshData, 5000);
    }
}

// 日付をフォーマット
function formatDate(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

// ===== 初期化実行 =====
init();