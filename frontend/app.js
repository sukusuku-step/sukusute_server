const state = {
    token: localStorage.getItem('sukusuteToken'),
    teacher: null,
    classes: [],
    selectedClassId: null,
    children: [],
    steps: {},
    stepIncreaseRanking: [],
    nearestNames: {},
    deviceStatuses: {},
    mlBehavior: {},
    mlAnomalies: {},
    mlRelations: {},
    mlDetailOpenStates: {},
    mlUpdatedAt: 0,
    mlChildSignature: '',
    selectedDate: new Date(),
    // 先生としてつけている端末かどうかは表示用のみの情報なのでブラウザに保存する。
    teacherFlags: new Set(JSON.parse(localStorage.getItem('sukusuteTeacherFlags') || '[]'))
};

// 画面表示に使う歩数ルール。カードと警告で同じ基準を使う。
const DEVICE_STATUS_STALE_MS = 60_000;
const ML_REFRESH_INTERVAL_MS = 30_000;

const ANOMALY_FEATURE_LABELS = {
    steps_10min: '10分間の歩数',
    activity_mean_proxy: '活動量',
    acc_std: '加速度のばらつき',
    gyro_mean: '角速度',
    mag_mean: '地磁気'
};

// フロントをAPIサーバーと別ホストで配信する場合の接続先。
// 同じFastAPIサーバーから配信する場合は '' にすると相対URLになる。
const API_BASE_URL = 'http://49.212.151.94:3000';

let refreshTimer = null;
let refreshInProgress = false;
// 児童ごとのスロット風アニメーションの進行状況（連続更新時に前回分を打ち切るために使う）。
const stepAnimationState = new Map();

// 端末が先生用としてチェックされているかどうかを判定する。
function isTeacherFlag(childId) {
    return state.teacherFlags.has(childId);
}

// 先生フラグを切り替え、ブラウザへ保存する（表示専用でサーバーへは送らない）。
function setTeacherFlag(childId, isTeacher) {
    if (isTeacher) state.teacherFlags.add(childId); else state.teacherFlags.delete(childId);
    localStorage.setItem('sukusuteTeacherFlags', JSON.stringify([...state.teacherFlags]));
}

// 歩数が増えたことがひと目でわかるよう、スロットのように数字を回してから確定値へ着地させる。
function animateStepValue(element, childId, targetValue) {
    const previous = stepAnimationState.get(childId);
    if (previous && previous.raf) cancelAnimationFrame(previous.raf);
    if (!previous) {
        element.textContent = targetValue.toLocaleString();
        stepAnimationState.set(childId, { raf: null, lastValue: targetValue });
        return;
    }
    const startValue = previous.lastValue;
    if (startValue === targetValue) {
        element.textContent = targetValue.toLocaleString();
        stepAnimationState.set(childId, { raf: null, lastValue: targetValue });
        return;
    }
    const duration = 2200;
    const direction = targetValue > startValue ? 1 : -1;
    const startTime = performance.now();
    element.classList.add('step-spin');
    let displayValue = startValue;
    const step = (now) => {
        const progress = Math.min((now - startTime) / duration, 1);
        // 現在の数字から目標値へ向けて、少しずつ増減しながらくるくる回っているように見せる
        const eased = 1 - Math.pow(1 - progress, 3);
        const easedTarget = startValue + (targetValue - startValue) * eased;
        const jitter = Math.random() * Math.abs(targetValue - startValue) * 0.1 * direction;
        if (progress < 1) {
            displayValue = direction > 0
                ? Math.min(targetValue, Math.max(displayValue, Math.round(easedTarget + Math.max(jitter, 0))))
                : Math.max(targetValue, Math.min(displayValue, Math.round(easedTarget + Math.min(jitter, 0))));
            element.textContent = displayValue.toLocaleString();
            const raf = requestAnimationFrame(step);
            stepAnimationState.set(childId, { raf, lastValue: startValue });
        } else {
            element.textContent = targetValue.toLocaleString();
            element.classList.remove('step-spin');
            stepAnimationState.set(childId, { raf: null, lastValue: targetValue });
        }
    };
    requestAnimationFrame(step);
}

// ===== API通信と認証状態 =====

async function apiRequest(url, options = {}) {
    const requestUrl = /^https?:\/\//i.test(url)
        ? url
        : `${API_BASE_URL}${url.startsWith('/') ? url : `/${url}`}`;
    console.info('[ui] API request', options.method || 'GET', requestUrl);
    const headers = { ...(options.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    if (options.body) headers['Content-Type'] = 'application/json';
    // APIの応答が止まって画面の更新全体が待ち続けないようにする。
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);
    let response;
    try {
        response = await fetch(requestUrl, { ...options, headers, signal: controller.signal });
    } catch (error) {
        if (controller.signal.aborted) throw new Error(`API応答がタイムアウトしました: ${requestUrl}`);
        throw error;
    } finally {
        clearTimeout(timeoutId);
    }
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && state.token) {
        localStorage.removeItem('sukusuteToken');
        state.token = null;
        showLogin();
        throw new Error('ログインの有効期限が切れています。もう一度ログインしてください。');
    }
    if (!response.ok) {
        console.error('[ui] API error', response.status, requestUrl, body);
        const error = new Error(body.detail || `HTTP ${response.status}`);
        error.status = response.status;
        throw error;
    }
    console.info('[ui] API response', response.status, requestUrl);
    return body;
}

// ML結果はデータが十分にたまるまで404になり得るため、404だけは「未算出」として扱う。
async function apiRequestOptional(url) {
    try {
        return await apiRequest(url);
    } catch (error) {
        if (error.status === 404) return null;
        throw error;
    }
}

function relationKey(childId1, childId2) {
    return [Number(childId1), Number(childId2)].sort((a, b) => a - b).join(':');
}

function formatMlNumber(value, digits = 3) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
    return Number(value).toFixed(digits).replace(/\.?0+$/, '');
}

function formatConfidence(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
    const number = Number(value);
    return number <= 1 ? `${(number * 100).toFixed(1)}%` : `${number.toFixed(1)}%`;
}

function formatAnomalyChange(feature, comparison) {
    const label = ANOMALY_FEATURE_LABELS[feature] || feature;
    const current = Number(comparison.current);
    const baseline = Number(comparison.baseline_median);
    const percent = formatMlNumber(comparison.relative_diff_percent, 1);

    if (Math.abs(baseline) < 1e-6) {
        if (current > baseline) {
            return `${label}が普段より増えています`;
        }

        if (current < baseline) {
            return `${label}が普段より減っています`;
        }

        return `${label}が普段と異なる値になっています`;
    }

    if (current > baseline) {
        return `${label}が普段より${percent}%増えました`;
    }

    if (current < baseline) {
        return `${label}が普段より${percent}%減りました`;
    }

    return `${label}が普段と異なる値になっています`;
}

// behavior/activity、ベースライン、児童間distance/関連度をまとめて取得する。
// 推論自体が10分単位なので、5秒ごとの歩数更新とは分けて30秒に一度だけ取得する。
async function loadMlResults(force = false) {
    const childIds = state.children.map((child) => Number(child.child_id)).sort((a, b) => a - b);
    const signature = childIds.join(',');
    const now = Date.now();
    if (!force
        && signature === state.mlChildSignature
        && now - state.mlUpdatedAt < ML_REFRESH_INTERVAL_MS) {
        return;
    }

    const nextBehavior = {};
    const nextAnomalies = {};
    const nextRelations = {};

    await Promise.all(childIds.map(async (childId) => {
        const [behavior, anomaly] = await Promise.all([
            apiRequestOptional(`/api/ml/behavior/${childId}`),
            apiRequestOptional(`/api/ml/anomaly/${childId}`)
        ]);
        nextBehavior[childId] = behavior;
        nextAnomalies[childId] = anomaly;
    }));

    const relationRequests = [];
    for (let i = 0; i < childIds.length; i += 1) {
        for (let j = i + 1; j < childIds.length; j += 1) {
            const childId1 = childIds[i];
            const childId2 = childIds[j];
            relationRequests.push((async () => {
                const result = await apiRequestOptional(
                    `/api/ml/relation?child_id_1=${encodeURIComponent(childId1)}&child_id_2=${encodeURIComponent(childId2)}`
                );
                nextRelations[relationKey(childId1, childId2)] = result;
            })());
        }
    }
    await Promise.all(relationRequests);

    state.mlBehavior = nextBehavior;
    state.mlAnomalies = nextAnomalies;
    state.mlRelations = nextRelations;
    state.mlUpdatedAt = now;
    state.mlChildSignature = signature;
}

// 日付をAPIのクエリパラメータ形式へ変換する。
function dateQuery(date) {
    return `year=${date.getFullYear()}&month=${date.getMonth() + 1}&day=${date.getDate()}`;
}

// ===== ログイン画面とダッシュボード初期化 =====
// ログインAPIを呼び、成功したトークンをブラウザへ保存する。

async function login(username, password) {
    const result = await apiRequest('/api/auth/login', {
        method: 'POST', body: JSON.stringify({ username, password })
    });
    state.token = result.token;
    state.teacher = result;
    localStorage.setItem('sukusuteToken', state.token);
    showApp();
    await loadClasses();
}

// ダッシュボードを表示し、ログイン画面を隠す。
function showApp() {
    document.getElementById('loginView').classList.add('is-hidden');
    document.getElementById('appView').classList.remove('is-hidden');
}

// ログイン画面を表示し、認証が必要な画面を隠す。
function showLogin() {
    document.getElementById('loginView').classList.remove('is-hidden');
    document.getElementById('appView').classList.add('is-hidden');
}

// クラス一覧を読み込み、選択欄を更新してから児童データを再取得する。
async function loadClasses() {
    console.info('[ui] loading classes');
    const result = await apiRequest('/api/classes');
    state.classes = result.classes || [];
    document.getElementById('classSummary').innerHTML = state.classes.length
        ? state.classes.map((item) => `<span>${escapeHtml(item.name)}（${item.child_count}人）</span>`).join('')
        : '<span>クラスが登録されていません</span>';
    const selector = document.getElementById('classSelector');
    selector.innerHTML = '<option value="">全員の様子</option>' + state.classes
        .map((item) => `<option value="${item.class_id}">${escapeHtml(item.name)}　のようす</option>`).join('');
    selector.value = state.selectedClassId || '';
    await loadDashboard();
}

// ===== ダッシュボードのデータ取得と描画 =====
// 選択中のクラスと日付に対応する児童・歩数を取得して画面を更新する。

async function loadDashboard() {
    if (refreshInProgress) return;
    refreshInProgress = true;
    console.info('[ui] dashboard refresh started', {
        classId: state.selectedClassId,
        date: formatDate(state.selectedDate)
    });
    setMessage('refreshMessage', '更新中...');
    const classQuery = state.selectedClassId ? `?class_id=${state.selectedClassId}` : '';
    try {
        const children = await apiRequest(`/api/children${classQuery}`);
        state.children = children.children || [];
        state.stepIncreaseRanking = [];
        // 歩数や端末状態のAPIを待たず、DBの児童一覧を先に表示する。
        renderStudents();
        renderRanking();
        // 歩数と端末状態は、取得できた方から独立して画面へ反映する。
        const refreshResults = await Promise.allSettled([
            apiRequest(`/api/stats/today?${dateQuery(state.selectedDate)}`).then((stats) => {
                state.steps = Object.fromEntries(
                    (stats.student_ranking || []).map((item) => [item.child_id, item.steps || 0])
                );
                state.stepIncreaseRanking = stats.step_increase_ranking || [];
                state.nearestNames = Object.fromEntries(
                    (stats.nearest_children || []).map((item) => [item.child_id, item.name])
                );
                renderStudents();
                renderRanking();
                renderWarnings(stats.warnings || []);
            }),
            apiRequest('/api/device_status').then((deviceStatuses) => {
                state.deviceStatuses = Object.fromEntries(
                    (deviceStatuses.devices || []).map((item) => [item.child_id, item])
                );
                renderStudents();
            }),
            loadMlResults().then(() => {
                renderStudents();
                if (!document.getElementById('relationModal').classList.contains('is-hidden')) {
                    renderRelationSummary();
                }
            }).catch((error) => {
                // 歩数ダッシュボード全体はML API障害の影響で止めない。
                console.warn('[ui] ML refresh failed', error);
            })
        ]);
        const failedRefresh = refreshResults.find((result) => result.status === 'rejected');
        if (failedRefresh) throw failedRefresh.reason;
        setMessage('refreshMessage', `最終更新 ${new Date().toLocaleTimeString()}`);
        console.info('[ui] dashboard refresh completed', {
            children: state.children.length,
            steps: Object.keys(state.steps).length
        });
    } catch (error) {
        if (!state.children.length) {
            const studentGrid = document.getElementById('studentGrid');

            if (studentGrid) {
                studentGrid.innerHTML = '<div class="loading">児童データを取得できませんでした。</div>';
            }
        }

        setMessage('refreshMessage', 'ステータスの更新に失敗しました');
        console.error('[ui] dashboard refresh failed', error);
    } finally {
        refreshInProgress = false;
    }
}

// RSSIを携帯電話のアンテナ表示に合わせて4段階に変換する。
function getWifiSignalLevel(wifiRssi) {
    if (wifiRssi >= -55) return 4;
    if (wifiRssi >= -67) return 3;
    if (wifiRssi >= -75) return 2;
    if (wifiRssi >= -85) return 1;
    return 0;
}

// 児童を歩数順に並べ、歩数カードをHTMLへ描画する。カードはDOMを使い回し、歩数だけスロット風に更新する。
function renderStudents() {
    const grid = document.getElementById('studentGrid');
    if (!state.children.length) {
        grid.innerHTML = '<div class="loading">このクラスに児童データがありません</div>';
        return;
    }
    grid.querySelector('.loading')?.remove();
    const sorted = [...state.children].sort((a, b) => (state.steps[b.child_id] || 0) - (state.steps[a.child_id] || 0));
    const visibleIds = new Set(sorted.map((child) => child.child_id));
    grid.querySelectorAll('[data-student-card]').forEach((card) => {
        if (!visibleIds.has(Number(card.dataset.studentCard))) card.remove();
    });
    sorted.forEach((child, index) => {
        const deviceStatus = state.deviceStatuses[child.child_id];
        const statusAge = deviceStatus ? Date.now() - Date.parse(deviceStatus.updated_at) : Infinity;
        const isDeviceStatusFresh = statusAge >= 0 && statusAge < DEVICE_STATUS_STALE_MS;
        const currentDeviceStatus = isDeviceStatusFresh ? deviceStatus : null;
        const wifiSignalLevel = currentDeviceStatus ? getWifiSignalLevel(currentDeviceStatus.wifi_rssi) : 0;
        const wifiRssiLabel = currentDeviceStatus ? `${currentDeviceStatus.wifi_rssi} dBm` : '接続なし';
        const wifiDescription = currentDeviceStatus
            ? `Wi-Fi電波強度 ${wifiSignalLevel}/4、${wifiRssiLabel}`
            : 'Wi-Fi電波強度 接続なし';
        const wifiBars = [1, 2, 3, 4].map((barNumber) =>
            `<span class="wifi-signal-bar${barNumber <= wifiSignalLevel ? ' is-active' : ''}"></span>`
        ).join('');

        const steps = state.steps[child.child_id] || 0;
        const isTeacher = isTeacherFlag(child.child_id);
        const nameHtml = `${escapeHtml(child.name || `児童${child.child_id}`)}
                            ${isTeacher ? 
                                '<span class="teacher-badge" title="先生の端末">🧑\u200d🏫 先生</span>' : ''
                            }`;
        
        let card = grid.querySelector(`[data-student-card="${child.child_id}"]`);
        if (!card) {
            card = document.createElement('article');
            card.className = 'student-card';
            card.dataset.studentCard = String(child.child_id);
            card.innerHTML = `
                <div class="student-name"></div>
                <div class="student-steps">歩数：<strong class="step-number"></strong></div>
                <div class="device-status"></div>
                <div class="student-status"></div>
                <section class="ml-summary" aria-label="推論結果"></section>`;
        }
        card.classList.toggle('has-telemetry', Boolean(currentDeviceStatus));
        card.querySelector('.student-name').innerHTML = nameHtml;
        const nearestName = state.nearestNames[child.child_id];
        let nearestPerson = card.querySelector('.nearest-person');
        if (nearestName) {
            if (!nearestPerson) {
                nearestPerson = document.createElement('div');
                nearestPerson.className = 'nearest-person';
                card.querySelector('.student-steps').insertAdjacentElement('afterend', nearestPerson);
            }
            nearestPerson.textContent = `最も近くにいる人：${nearestName}`;
        } else {
            nearestPerson?.remove();
        }
        card.querySelector('.device-status').innerHTML = `
            <span>BATTERY : ${currentDeviceStatus ? `${currentDeviceStatus.battery}%` : 'データなし'}${isDeviceStatusFresh ? '' : '<span class="device-warning" role="img" aria-label="端末データが1分以上更新されていません" title="端末データが1分以上更新されていません">!</span>'}</span>
            <span class="wifi-status" role="img" aria-label="${wifiDescription}" title="${wifiDescription}">
                <span class="wifi-signal" aria-hidden="true">${wifiBars}</span>
                <span>Wi-Fi ${wifiRssiLabel}</span>
            </span>`;
        card.querySelector('.student-status').className = 'student-status';
        card.querySelector('.student-status').innerHTML = '';

        const behavior = state.mlBehavior[child.child_id];
        const anomaly = state.mlAnomalies[child.child_id];

        const currentBaselineDetails = card.querySelector('.baseline-details');
        const currentRelationDetails = card.querySelector('.relation-details');

        if (!state.mlDetailOpenStates[child.child_id]) {
            state.mlDetailOpenStates[child.child_id] = {
                baseline: false,
                relation: false
            };
        }

        if (currentBaselineDetails) {
            state.mlDetailOpenStates[child.child_id].baseline = currentBaselineDetails.open;
        }

        if (currentRelationDetails) {
            state.mlDetailOpenStates[child.child_id].relation = currentRelationDetails.open;
        }

        const anomalyWarnings = anomaly?.comparisons
            ? Object.entries(anomaly.comparisons).filter(([, comparison]) => comparison.warning)
            : [];
        
        const relationRows = state.children
            .filter((other) => other.child_id !== child.child_id)
            .map((other) => {
                const relation = state.mlRelations[relationKey(child.child_id, other.child_id)];
                return `
                    <div class="relation-score-row">
                        <strong>${escapeHtml(other.name || `児童${other.child_id}`)}</strong>
                        <span>距離: ${relation ? escapeHtml(relation.evaluated) : '未算出'}</span>
                        <span>信頼度: ${relation ? formatConfidence(relation.confidence) : '-'}</span>
                        <span>関連度: ${relation ? formatMlNumber(relation.score) : '-'}</span>
                    </div>`;
            }).join('');

        card.querySelector('.ml-summary').innerHTML = `
            ${anomaly?.warning ? `
                <article class="warning-item" role="alert">
                    <strong>⚠ 普段と異なる状態を検出しました</strong>
                    <span>直近10分の特徴量がベースラインから10%以上離れています。</span>
                    <small>${anomalyWarnings.map(([feature, comparison]) =>
                        escapeHtml(formatAnomalyChange(feature, comparison))
                    ).join('<br>')}</small>
                </article>
            ` : ''}
            <div class="ml-section">
                <h3>最新のステータス</h3>
                ${behavior ? `
                    <div class="ml-result-grid">
                        <span>姿勢状態</span><strong>${escapeHtml(behavior.behavior_acce)}</strong><small>${formatConfidence(behavior.behavior_acce_confidence)}での推論</small>
                        <span>走行状態</span><strong>${escapeHtml(behavior.behavior_pedo)}</strong><small>${formatConfidence(behavior.behavior_pedo_confidence)}での推論</small>
                        <span>活動量</span><strong>${escapeHtml(behavior.activity_level)} / 5</strong><small>${formatConfidence(behavior.activity_confidence)}での推論</small>
                    </div>` : '<p class="ml-empty">得られたステータスはまだありません</p>'}
            </div>
            <details class="relation-details" ${state.mlDetailOpenStates[child.child_id]?.relation ? 'open' : ''}>
                <summary>他児童との距離状態・関連度スコア</summary>
                <div class="relation-score-list">
                    ${relationRows || '<p class="ml-empty">比較対象の児童がいません</p>'}
                </div>
            </details>
            <details class="baseline-details" ${state.mlDetailOpenStates[child.child_id]?.baseline ? 'open' : ''}>
                <summary>この児童の普段のステータス（ベースライン）</summary>
                ${behavior ? `
                    <div class="baseline-grid">
                        <span>歩数/10分</span><span>中央値 ${formatMlNumber(behavior.baseline_steps_10min_median)} / ばらつき ${formatMlNumber(behavior.baseline_steps_10min_mad_scale)}</span>
                        <span>活動量</span><span>中央値 ${formatMlNumber(behavior.baseline_activity_mean_proxy_median)} / ばらつき ${formatMlNumber(behavior.baseline_activity_mean_proxy_mad_scale)}</span>
                        <span>加速度</span><span>中央値 ${formatMlNumber(behavior.baseline_acc_std_median)} / ばらつき ${formatMlNumber(behavior.baseline_acc_std_mad_scale)}</span>
                        <span>ジャイロ</span><span>中央値 ${formatMlNumber(behavior.baseline_gyro_mean_median)} / ばらつき ${formatMlNumber(behavior.baseline_gyro_mean_mad_scale)}</span>
                        <span>地磁気</span><span>中央値 ${formatMlNumber(behavior.baseline_mag_mean_median)} / ばらつき ${formatMlNumber(behavior.baseline_mag_mean_mad_scale)}</span>
                    </div>` : '<p class="ml-empty">ベースラインは未算出です</p>'}
            </details>`;

        const baselineDetails = card.querySelector('.baseline-details');
        const relationDetails = card.querySelector('.relation-details');

        baselineDetails?.addEventListener('toggle', () => {
            if (!state.mlDetailOpenStates[child.child_id]) {
                state.mlDetailOpenStates[child.child_id] = {
                    baseline: false,
                    relation: false
                };
            }
            state.mlDetailOpenStates[child.child_id].baseline = baselineDetails.open;
        });

        relationDetails?.addEventListener('toggle', () => {
            if (!state.mlDetailOpenStates[child.child_id]) {
                state.mlDetailOpenStates[child.child_id] = {
                    baseline: false,
                    relation: false
                };
            }
            state.mlDetailOpenStates[child.child_id].relation = relationDetails.open;
        });

        const referenceNode = grid.children[index];
        if (referenceNode !== card) grid.insertBefore(card, referenceNode || null);
        animateStepValue(card.querySelector('.step-number'), child.child_id, steps);
    });
}

// 現在表示中の児童から直近1分の歩数増加上位5名を描画する。
function renderRanking() {
    const visibleChildIds = new Set(state.children.map((child) => child.child_id));
    const ranking = state.stepIncreaseRanking
        .filter((item) => visibleChildIds.has(item.child_id))
        .slice(0, 5);
    document.querySelectorAll('#rankingList li').forEach((item, index) => {
        const entry = ranking[index];
        item.innerHTML = entry
            ? `<span>${index + 1}.</span><strong>${escapeHtml(entry.name || `児童${entry.child_id}`)}</strong>`
            : `<span>${index + 1}.</span><strong>-</strong>`;
    });
}

// 警告を児童IDごとに最新1件へ絞り、現在のクラスの警告だけを表示する。
function renderWarnings(warnings) {
    const warningList = document.getElementById('warningList');
    const visibleChildIds = new Set(state.children.map((child) => child.child_id));
    const latestWarnings = new Map();
    for (const warning of warnings) {
        const previous = latestWarnings.get(warning.child_id);
        if (!previous || new Date(warning.date).getTime() >= new Date(previous.date).getTime()) {
            latestWarnings.set(warning.child_id, warning);
        }
    }
    const visibleWarnings = [...latestWarnings.values()]
        .filter((warning) => visibleChildIds.has(warning.child_id));
    if (!visibleWarnings.length) {
        warningList.innerHTML = '<p class="warning-empty">異常はありません</p>';
        return;
    }
    warningList.innerHTML = visibleWarnings.map((warning) => `
        <article class="warning-item">
            <strong>${escapeHtml(warning.name)}</strong>
            <span>歩数 ${warning.current_steps.toLocaleString()}歩</span>
            <small>普段の${warning.percent}%（平均 ${warning.average_steps.toLocaleString()}歩）</small>
        </article>`).join('');
}

// クラス管理情報を取得してから、クラス管理モーダルを開く。
async function openClassModal() {
    try {
        await refreshClassList();
        setMessage('classMessage', '');
        openModal('classModal');
    } catch (error) {
        setMessage('classMessage', error.message);
    }
}

// クラス一覧と児童の所属クラス選択肢をモーダルへ描画する。
async function refreshClassList() {
    const result = await apiRequest('/api/classes');
    document.getElementById('classList').innerHTML = (result.classes || []).map((item) => `
        <div class="class-row"><span>${escapeHtml(item.name)}（${item.child_count}人）</span>
        <button type="button" data-rename-class="${item.class_id}">名前変更</button></div>`).join('');
    const children = await apiRequest('/api/children');
    document.getElementById('childAssignments').innerHTML = (children.children || []).map((child) => `
        <label class="class-row"><span>${escapeHtml(child.name)}</span>
        <select data-child-class="${child.child_id}">
            <option value="">未所属</option>
            ${(result.classes || []).map((item) => `<option value="${item.class_id}" ${item.class_id === child.class_id ? 'selected' : ''}>${escapeHtml(item.name)}</option>`).join('')}
        </select></label>`).join('');
}

// 現在の児童間について、distance_inferの推論結果と関連度スコアを一覧表示する。
function renderRelationSummary() {
    const graph = document.getElementById('relationGraph');
    const rows = [];
    for (let i = 0; i < state.children.length; i += 1) {
        for (let j = i + 1; j < state.children.length; j += 1) {
            const child1 = state.children[i];
            const child2 = state.children[j];
            const relation = state.mlRelations[relationKey(child1.child_id, child2.child_id)];
            rows.push(`
                <div class="relation-pair">
                    <strong>${escapeHtml(child1.name)} ↔ ${escapeHtml(child2.name)}</strong>
                    <span>距離状態: ${relation ? escapeHtml(relation.evaluated) : '未算出'}</span>
                    <span>信頼度: ${relation ? formatConfidence(relation.confidence) : '-'}</span>
                    <span>関連度: ${relation ? formatMlNumber(relation.score) : '-'}</span>
                </div>`);
        }
    }
    graph.innerHTML = rows.length ? rows.join('') : '<span>比較できる児童データがありません</span>';
}

async function openRelationModal() {
    openModal('relationModal');
    document.getElementById('relationGraph').innerHTML = '<span>結果を読み込み中...</span>';
    try {
        await loadMlResults(true);
        renderStudents();
        renderRelationSummary();
    } catch (error) {
        document.getElementById('relationGraph').innerHTML =
            `<span>結果を取得できませんでした: ${escapeHtml(error.message)}</span>`;
    }
}

// 生徒管理情報を取得してから、生徒管理モーダルを開く。
async function openStudentManageModal() {
    try {
        await refreshStudentManageList();
        setMessage('studentManageMessage', '');
        openModal('studentManageModal');
    } catch (error) {
        setMessage('studentManageMessage', error.message);
    }
}

// 全児童のクラス割り振りと先生チェックを生徒管理モーダルへ描画する。
async function refreshStudentManageList() {
    const [childrenResult, classesResult] = await Promise.all([
        apiRequest('/api/children'),
        apiRequest('/api/classes')
    ]);
    const classes = classesResult.classes || [];
    document.getElementById('studentManageList').innerHTML = (childrenResult.children || []).map((child) => {
        const isTeacher = isTeacherFlag(child.child_id);
        return `<div class="student-manage-row ${isTeacher ? 'is-teacher' : ''}" data-manage-row="${child.child_id}">
            <span class="student-manage-name">${escapeHtml(child.name)}${isTeacher ? '<span class="teacher-badge" title="先生の端末">🧑‍🏫 先生</span>' : ''}</span>
            <select data-manage-class="${child.child_id}">
                <option value="">未所属</option>
                ${classes.map((item) => `<option value="${item.class_id}" ${item.class_id === child.class_id ? 'selected' : ''}>${escapeHtml(item.name)}</option>`).join('')}
            </select>
            <label class="teacher-checkbox">
                <input type="checkbox" data-manage-teacher="${child.child_id}" ${isTeacher ? 'checked' : ''}>
                先生
            </label>
        </div>`;
    }).join('');
}

// 指定したモーダルだけを表示する。
function openModal(id) {
    document.getElementById('modalLayer').classList.remove('is-hidden');
    document.querySelectorAll('.modal-card').forEach((modal) => modal.classList.add('is-hidden'));
    document.getElementById(id).classList.remove('is-hidden');
}

// 開いているモーダルを閉じる。
function closeModal() {
    document.getElementById('modalLayer').classList.add('is-hidden');
}

// 現在ログイン中のユーザー名を初期値にして削除画面を開く。
function openAccountDeleteModal() {
    document.getElementById('deleteUsername').value = state.teacher?.username || '';
    document.getElementById('deletePassword').value = '';
    setMessage('deleteMessage', '');
    openModal('accountDeleteModal');
}

// 指定したメッセージ領域へ操作結果を表示する。
function setMessage(id, message) {
    document.getElementById(id).textContent = message;
}

// APIから受け取った文字列をHTMLへ安全に埋め込める形へ変換する。
function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (character) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    }[character]));
}

// date inputへ設定できるYYYY-MM-DD文字列を作る。
function formatDate(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

// ===== 画面フォームとメニューのイベント処理 =====

document.getElementById('loginForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    setMessage('loginMessage', '');
    try {
        await login(document.getElementById('loginUsername').value, document.getElementById('loginPassword').value);
    } catch (error) {
        setMessage('loginMessage', error.message);
    }
});

document.getElementById('registerForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    setMessage('registerMessage', '');
    try {
        await apiRequest('/api/auth/register', { method: 'POST', body: JSON.stringify({
            username: document.getElementById('registerUsername').value,
            password: document.getElementById('registerPassword').value
        }) });
        document.getElementById('loginUsername').value = document.getElementById('registerUsername').value;
        document.getElementById('loginPassword').value = document.getElementById('registerPassword').value;
        document.getElementById('registerForm').classList.add('is-hidden');
        document.getElementById('loginForm').classList.remove('is-hidden');
        setMessage('loginMessage', 'アカウントを作成しました。ログインしてください。');
    } catch (error) {
        setMessage('registerMessage', error.message);
    }
});

document.getElementById('showRegisterButton').addEventListener('click', () => {
    document.getElementById('loginForm').classList.add('is-hidden');
    document.getElementById('registerForm').classList.remove('is-hidden');
});
document.getElementById('showLoginButton').addEventListener('click', () => {
    document.getElementById('registerForm').classList.add('is-hidden');
    document.getElementById('loginForm').classList.remove('is-hidden');
});
document.getElementById('menuButton').addEventListener('click', () => document.getElementById('menuPanel').classList.add('is-open'));
document.getElementById('closeMenuButton').addEventListener('click', () => document.getElementById('menuPanel').classList.remove('is-open'));
document.getElementById('openClassButton').addEventListener('click', () => { openClassModal(); });
document.querySelectorAll('[data-close-modal]').forEach((button) => button.addEventListener('click', closeModal));
document.querySelector('[data-action="class"]').addEventListener('click', () => { document.getElementById('menuPanel').classList.remove('is-open'); openClassModal(); });
document.querySelector('[data-action="student-manage"]').addEventListener('click', () => { document.getElementById('menuPanel').classList.remove('is-open'); openStudentManageModal(); });
document.querySelector('[data-action="relation"]').addEventListener('click', () => { document.getElementById('menuPanel').classList.remove('is-open'); openRelationModal(); });
document.querySelector('[data-action="refresh"]').addEventListener('click', () => {
    document.getElementById('menuPanel').classList.remove('is-open');
    console.info('[ui] manual refresh clicked');
    loadDashboard();
});
document.querySelector('[data-action="account-delete"]').addEventListener('click', () => { document.getElementById('menuPanel').classList.remove('is-open'); openAccountDeleteModal(); });
document.querySelector('[data-action="logout"]').addEventListener('click', async () => {
    try { await apiRequest('/api/auth/logout', { method: 'POST' }); } catch (error) { console.error(error); }
    localStorage.removeItem('sukusuteToken'); state.token = null; showLogin();
});
document.getElementById('classSelector').addEventListener('change', (event) => {
    state.selectedClassId = Number(event.target.value) || null;
    loadDashboard();
});
document.getElementById('dateSelector').value = formatDate(state.selectedDate);
document.getElementById('dateSelector').addEventListener('change', (event) => {
    state.selectedDate = new Date(`${event.target.value}T00:00:00`);
    loadDashboard();
});
document.getElementById('classForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    setMessage('classMessage', '');
    try {
        await apiRequest('/api/classes', { method: 'POST', body: JSON.stringify({ name: document.getElementById('newClassName').value }) });
        document.getElementById('newClassName').value = '';
        await refreshClassList();
        await loadClasses();
        setMessage('classMessage', 'クラスを追加しました。');
    } catch (error) {
        setMessage('classMessage', error.message);
    }
});
document.getElementById('classList').addEventListener('click', async (event) => {
    const button = event.target.closest('[data-rename-class]');
    if (!button) return;
    const name = prompt('新しいクラス名');
    if (!name) return;
    try {
        await apiRequest(`/api/classes/${button.dataset.renameClass}`, { method: 'PATCH', body: JSON.stringify({ name }) });
        await refreshClassList();
        await loadClasses();
    } catch (error) { alert(error.message); }
});
document.getElementById('childAssignments').addEventListener('change', async (event) => {
    const select = event.target.closest('[data-child-class]');
    if (!select) return;
    await apiRequest(`/api/children/${select.dataset.childClass}/class`, {
        method: 'PATCH', body: JSON.stringify({ class_id: Number(select.value) || null })
    });
    await loadClasses();
    await refreshClassList();
});
document.getElementById('studentManageList').addEventListener('change', async (event) => {
    const select = event.target.closest('[data-manage-class]');
    if (select) {
        try {
            await apiRequest(`/api/children/${select.dataset.manageClass}/class`, {
                method: 'PATCH', body: JSON.stringify({ class_id: Number(select.value) || null })
            });
            await loadClasses();
        } catch (error) {
            setMessage('studentManageMessage', error.message);
        }
        return;
    }
    const checkbox = event.target.closest('[data-manage-teacher]');
    if (checkbox) {
        const childId = Number(checkbox.dataset.manageTeacher);
        setTeacherFlag(childId, checkbox.checked);
        await refreshStudentManageList();
        renderStudents();
    }
});
document.getElementById('accountDeleteForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!confirm('アカウントを削除しますか？この操作は取り消せません。')) return;
    try {
        await apiRequest('/api/auth/account', {
            method: 'DELETE',
            body: JSON.stringify({
                username: document.getElementById('deleteUsername').value,
                password: document.getElementById('deletePassword').value
            })
        });
        localStorage.removeItem('sukusuteToken');
        state.token = null;
        closeModal();
        showLogin();
        setMessage('loginMessage', 'アカウントを削除しました。');
    } catch (error) {
        setMessage('deleteMessage', error.message);
    }
});

// 保存済みトークンがある場合は、ログイン画面を経由せず復元を試みる。
if (state.token) {
    showApp();
    loadClasses().catch(() => { localStorage.removeItem('sukusuteToken'); state.token = null; showLogin(); });
}

refreshTimer = setInterval(() => {
    if (state.token && !document.hidden) {
        console.info('[ui] automatic refresh triggered');
        loadDashboard();
    }
}, 5000);