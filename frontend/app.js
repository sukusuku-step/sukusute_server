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

    // DBデータの実際の最終更新時刻
    dataFreshness: {
        serverStartedAt: null,
        childData: {},
        childDistance: {},
        mlProgress: {},
    },

    mlBehavior: {},
    mlAnomalies: {},
    mlRelations: {},

    mlDetailOpenStates: {},
    mlUpdatedAt: 0,
    mlChildSignature: '',

    selectedDate: new Date(),

    teacherFlags: new Set(
        JSON.parse(
            localStorage.getItem(
                'sukusuteTeacherFlags'
            ) || '[]'
        )
    )
};

const DISPLAY_MODE_KEY = 'sukusuteDisplayMode';

const DEVICE_STATUS_STALE_MS = 60_000;

// 歩数・最も近い人
const SENSOR_DATA_STALE_MS = 60_000;

// ML推論
const ML_RESULT_STALE_MS = 15 * 60_000;
const ML_REFRESH_INTERVAL_MS = 30_000;

const ANOMALY_FEATURE_LABELS = {
    steps_10min: '10分間の歩数',
    activity_mean_proxy: '活動量',
    acc_std: '加速度のばらつき',
    gyro_mean: '角速度',
    mag_mean: '地磁気'
};

// APIは画面と同じFastAPIサーバーへ送る。
const API_BASE_URL = '';

function setDisplayMode(mode) {
    const isSquare = mode === 'square';
    document.body.classList.toggle('square-mode', isSquare);
    localStorage.setItem(DISPLAY_MODE_KEY, isSquare ? 'square' : 'horizontal');
    const toggleButton = document.getElementById('displayModeToggleButton');
    toggleButton?.classList.toggle('is-square', isSquare);
    toggleButton?.setAttribute('aria-label', `UIを変更（現在：${isSquare ? '四角表示' : '横型表示'}）`);
    toggleButton?.setAttribute('title', `現在：${isSquare ? '四角表示' : '横型表示'}`);
    toggleButton?.querySelectorAll('[data-display-mode]').forEach((button) => {
        button.setAttribute('aria-pressed', String(button.dataset.displayMode === (isSquare ? 'square' : 'horizontal')));
    });
    document.querySelector('[data-action="display-horizontal"]')?.setAttribute('aria-pressed', String(!isSquare));
    document.querySelector('[data-action="display-square"]')?.setAttribute('aria-pressed', String(isSquare));
}

setDisplayMode(localStorage.getItem(DISPLAY_MODE_KEY) || 'horizontal');

let refreshTimer = null;
let refreshInProgress = false;
let openStudentDetailChildId = null;

// 児童ごとのスロット風アニメーションの進行状況（連続更新時に前回分を打ち切るために使う）。
const stepAnimationState = new Map();
let signageScrollInterval = 0;
let signageScrollRetryTimer = 0;
let signageScrollPauseUntil = 0;
let signageScrollDirection = 1;

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

function parseTimestamp(value) {
    if (!value) return null;

    const timestamp = Date.parse(value);

    return Number.isFinite(timestamp)
        ? timestamp
        : null;
}

function getEffectiveFreshnessAge(valueTimestamp) {
    const now = Date.now();
    const dataTime = parseTimestamp(valueTimestamp);
    const serverStartedAt = parseTimestamp(state.dataFreshness.serverStartedAt);

    if (serverStartedAt === null) {
        return 0;
    }

    // サーバ起動時点からDBの値を読んでいるだけなら色を変える。
    if (dataTime === null) {
        return Infinity;
    }

    if (dataTime <= serverStartedAt) {
        return Infinity;
    }

    return Math.max(0, now - dataTime);
}

function isFreshnessStale(valueTimestamp, staleMs) {
    return (
        getEffectiveFreshnessAge(valueTimestamp) >= staleMs
    );
}

function isMlResultStale(valueTimestamp) {
    const resultTime = parseTimestamp(valueTimestamp);
    if (resultTime === null) return true;
    return Math.max(0, Date.now() - resultTime) >= ML_RESULT_STALE_MS;
}

function staleClass(stale) {
    return stale
        ? ' is-stale-value'
        : '';
}

function formatAnomalyChange(feature, comparison) {
    const label = ANOMALY_FEATURE_LABELS[feature] || feature;
    const current = Number(comparison.current);
    const baseline = Number(comparison.baseline_median);
    const percent = formatMlNumber(comparison.relative_diff_percent, 1);

    if (Math.abs(baseline) < 1e-6) {
        if (current > baseline) {
            return `・${label}が普段よりも増加`;
        }

        if (current < baseline) {
            return `・${label}が普段よりも減少`;
        }

        return `・${label}が普段と大きく異なる数値`;
    }

    if (current > baseline) {
        return `・${label}が普段よりも${percent}%増加`;
    }

    if (current < baseline) {
        return `・${label}が普段よりも${percent}%減少`;
    }

    return `・${label}が普段と大きく異なる数値`;
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
    renderModelAnomalyWarnings();
}

// 日付をAPIのクエリパラメータ形式へ変換する。
function dateQuery(date) {
    return `year=${date.getFullYear()}&month=${date.getMonth() + 1}&day=${date.getDate()}`;
}

function isToday(date) {
    const now = new Date();
    return date.getFullYear() === now.getFullYear()
        && date.getMonth() === now.getMonth()
        && date.getDate() === now.getDate();
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

    const menuUsername = document.getElementById('menuUsername');
    if (menuUsername) {
        menuUsername.textContent = state.teacher?.username || '';
    }
}

function closeMenu() {
    const menuPanel = document.getElementById('menuPanel');

    menuPanel.classList.remove('is-open');
    menuPanel.setAttribute('aria-hidden', 'true');
}

async function openConfigModal() {
    setMessage('configMessage', '');
    const config = await apiRequest('/api/ml/config');

    const activityTotalMinutes = Number(config.activity_max_data_minutes) || 0;
    document.getElementById('configActivityMaxHours').value = Math.floor(activityTotalMinutes / 60);
    document.getElementById('configActivityMaxMinutes').value = activityTotalMinutes % 60;

    document.getElementById('configAnomalyThreshold').value = config.anomaly_threshold_percent;
    const totalMinutes = Number(config.baseline_min_data_minutes) || 0;

    document.getElementById('configBaselineMinHours').value = Math.floor(totalMinutes / 60);
    document.getElementById('configBaselineMinMinutes').value = totalMinutes % 60;

    document.getElementById('configBaselineMaxDays').value = config.baseline_max_days;

    document.getElementById('configRelatednessMaxHistory').value = config.relatedness_max_history;

    closeMenu();
    openModal('configModal');
}

// ログイン画面を表示し、認証が必要な画面を隠す。
function showLogin() {
    closeMenu(); // ログアウト時は必ずメニュー欄を閉じる

    document.getElementById('loginView').classList.remove('is-hidden');
    document.getElementById('appView').classList.add('is-hidden');

    const menuUsername = document.getElementById('menuUsername');
    if (menuUsername) {
        menuUsername.textContent = '';
    }
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
            apiRequest(
                `/api/stats/today?${dateQuery(
                    state.selectedDate
                )}`
            ).then((stats) => {
                state.steps = Object.fromEntries(
                    (stats.student_ranking || []).map(
                        (item) => [
                            item.child_id,
                            item.steps || 0
                        ]
                    )
                );

                state.stepIncreaseRanking =
                    stats.step_increase_ranking || [];

                state.nearestNames = Object.fromEntries(
                    (stats.nearest_children || []).map(
                        (item) => [
                            item.child_id,
                            item.name
                        ]
                    )
                );

                renderStudents();
                renderRanking();
                renderWarnings(
                    stats.warnings || []
                );
            }),

            apiRequest(
                '/api/device_status'
            ).then((deviceStatuses) => {
                state.deviceStatuses =
                    Object.fromEntries(
                        (
                            deviceStatuses.devices
                            || []
                        ).map(
                            (item) => [
                                item.child_id,
                                item
                            ]
                        )
                    );

                renderStudents();
            }),

            apiRequest(
                '/api/data_freshness'
            ).then((freshness) => {
                state.dataFreshness = {
                    serverStartedAt:
                        freshness.server_started_at,

                    childData:
                        freshness.child_data || {},

                    childDistance:
                        freshness.child_distance || {},

                    mlProgress:
                        freshness.ml_progress || {},
                };

                renderStudents();
            }),

            loadMlResults()
                .then(() => {
                    renderStudents();

                    if (
                        !document
                            .getElementById(
                                'relationModal'
                            )
                            .classList
                            .contains('is-hidden')
                    ) {
                        renderRelationSummary();
                    }
                })
                .catch((error) => {
                    console.warn(
                        '[ui] ML refresh failed',
                        error
                    );
                }),
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
                studentGrid.innerHTML = '<div class="loading">子どものデータを取得できませんでした。</div>';
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
    const isSelectedToday = isToday(state.selectedDate);
    if (!state.children.length) {
        grid.innerHTML = '<div class="loading">このクラスに子どものデータがありません</div>';
        ensureSignageAutoScroll();
        return;
    }
    grid.querySelector('.loading')?.remove();
    const previousPositions = new Map();
    grid.querySelectorAll('[data-student-card]').forEach((card) => {
        card.getAnimations()
            .filter((animation) => animation.id === 'student-reorder')
            .forEach((animation) => animation.cancel());
        const rect = card.getBoundingClientRect();
        previousPositions.set(Number(card.dataset.studentCard), { left: rect.left, top: rect.top });
    });
    const sorted = [...state.children].sort((a, b) => (state.steps[b.child_id] || 0) - (state.steps[a.child_id] || 0));
    const visibleIds = new Set(sorted.map((child) => child.child_id));
    grid.querySelectorAll('[data-student-card]').forEach((card) => {
        if (!visibleIds.has(Number(card.dataset.studentCard))) card.remove();
    });
    sorted.forEach((child, index) => {
        const deviceStatus = state.deviceStatuses[child.child_id];
        const statusAge = deviceStatus ? Date.now() - Date.parse(deviceStatus.updated_at) : Infinity;
        const isDeviceStatusFresh = statusAge >= 0 && statusAge < DEVICE_STATUS_STALE_MS;
        const currentDeviceStatus = isSelectedToday && isDeviceStatusFresh ? deviceStatus : null;
        const wifiSignalLevel = currentDeviceStatus ? getWifiSignalLevel(currentDeviceStatus.wifi_rssi) : 0;
        const wifiRssiLabel = currentDeviceStatus ? `${currentDeviceStatus.wifi_rssi} dBm` : ' : 接続なし';

        const wifiDescription = currentDeviceStatus
            ? `Wi-Fi電波強度 ${wifiSignalLevel}/4、${wifiRssiLabel}`
            : 'Wi-Fi電波強度 接続なし';

        const wifiBars = [1, 2, 3, 4].map((barNumber) =>
            `<span class="wifi-signal-bar${barNumber <= wifiSignalLevel ? ' is-active' : ''}"></span>`
        ).join('');

        const steps = state.steps[child.child_id] || 0;

        const latestChildDataAt = state.dataFreshness.childData[child.child_id];

        const stepsAreStale = isFreshnessStale(
                latestChildDataAt,
                SENSOR_DATA_STALE_MS
        );

        const isTeacher = isTeacherFlag(child.child_id);
        const nameHtml = `${escapeHtml(child.name || `子ども${child.child_id}`)}
                            ${isTeacher ? 
                                '<span class="teacher-badge" title="先生の端末">🧑\u200d🏫 先生</span>' : ''
                            }`;
        
        let card = grid.querySelector(`[data-student-card="${child.child_id}"]`);
        if (!card) {
            card = document.createElement('article');
            card.className = 'student-card';
            card.dataset.studentCard = String(child.child_id);
            card.addEventListener('click', () => openStudentDetailModal(child.child_id));
            card.innerHTML = `
                <div class="student-name"></div>
                <div class="student-steps">歩数：<strong class="step-number"></strong></div>
                <div class="device-status"></div>
                <div class="student-status"></div>
                <section class="ml-summary" aria-label="推論結果"></section>`;
        }
            card.dataset.palette = String((child.child_id - 1) % 8);
        card.classList.toggle('has-telemetry', Boolean(currentDeviceStatus));
        card.classList.toggle('has-model-warning', state.mlAnomalies[child.child_id]?.warning === true);
        card.querySelector('.student-name').innerHTML = nameHtml;

        const latestDistanceDataAt = state.dataFreshness.childDistance[child.child_id];
        const nearestIsStale = isFreshnessStale(latestDistanceDataAt, SENSOR_DATA_STALE_MS);
        const nearestName = state.nearestNames[child.child_id];

        let nearestPerson = card.querySelector('.nearest-person');

        const studentStepsElement = card.querySelector('.student-steps');
        studentStepsElement.classList.toggle('is-stale-value', stepsAreStale);
        studentStepsElement.title = stepsAreStale ? '歩数データが1分以上更新されていません' : '';

        if (!nearestPerson) {
            nearestPerson = document.createElement('div');
            nearestPerson.className = 'nearest-person';

            card
                .querySelector(
                    '.student-steps'
                )
                .insertAdjacentElement(
                    'afterend',
                    nearestPerson
                );
        }

        nearestPerson.textContent =
            `最も近くにいる人：${
                nearestName || 'データなし'
            }`;

        nearestPerson.classList.toggle(
            'is-stale-value',
            nearestIsStale
        );

        nearestPerson.title =
            nearestIsStale
                ? '距離データが1分以上更新されていません'
                : '';

        const deviceStatusElement = card.querySelector('.device-status');
        deviceStatusElement.hidden = !isSelectedToday;
        deviceStatusElement.innerHTML = isSelectedToday ? `
            <span>BATTERY : ${currentDeviceStatus ? `${currentDeviceStatus.battery}%` : 'データなし'}${isDeviceStatusFresh ? '' : '<span class="device-warning" role="img" aria-label="端末データが1分以上更新されていません" title="端末データが1分以上更新されていません">!</span>'}</span>
            <span class="wifi-status" role="img" aria-label="${wifiDescription}" title="${wifiDescription}">
                <span class="wifi-signal" aria-hidden="true">${wifiBars}</span>
                <span>Wi-Fi ${wifiRssiLabel}</span>
            </span>` : '';
        card.querySelector('.student-status').className = 'student-status';
        card.querySelector('.student-status').innerHTML = '';

        const behavior = state.mlBehavior[child.child_id];
        const behaviorIsStale = behavior ? isMlResultStale(behavior.date) : false;

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
                const relationIsStale = relation ? isMlResultStale(relation.date) : false;

                return `
                    <div class="relation-score-row${staleClass(relationIsStale)}">
                        <strong>${escapeHtml(other.name || `子ども${other.child_id}`)}</strong>
                        <span>距離: ${relation ? escapeHtml(relation.evaluated) : '未算出'}</span>
                        <span>信頼度: ${relation ? formatConfidence(relation.confidence) : '-'}</span>
                        <span>関連度: ${relation ? formatMlNumber(relation.score) : '-'}</span>
                    </div>
                `;
            }).join('');

        card.querySelector('.ml-summary').innerHTML = `
            ${anomaly?.warning ? `
                <article class="warning-item" role="alert">
                    <strong>⚠ 普段と異なる状態を検出しました</strong>
                    <span>
                        直近の10分間でのデータが普段の値から
                        ${formatMlNumber(anomaly.threshold_percent, 1)}%以上外れています。    
                    </span>
                    <small>${anomalyWarnings.map(([feature, comparison]) =>
                        escapeHtml(formatAnomalyChange(feature, comparison))
                    ).join('<br>')}</small>
                </article>
            ` : ''}
            <div class="ml-section">
                <h3>最新のステータス</h3>
                ${behavior ? `
                    <div class="ml-result-grid${staleClass(behaviorIsStale)}" ${behaviorIsStale ? 'title="推論結果が15分以上更新されていません"' : ''}>
                        <span>姿勢状態</span><strong>${escapeHtml(behavior.behavior_acce)}</strong><small>${formatConfidence(behavior.behavior_acce_confidence)}での推論</small>
                        <span>走行状態</span><strong>${escapeHtml(behavior.behavior_pedo)}</strong><small>${formatConfidence(behavior.behavior_pedo_confidence)}での推論</small>
                        <span>活動量</span><strong>${escapeHtml(behavior.activity_level)} / 5</strong><small>${formatConfidence(behavior.activity_confidence)}での推論</small>
                    </div>` : '<p class="ml-empty">計測したデータがまだありません</p>'}
            </div>
            <details class="relation-details" ${state.mlDetailOpenStates[child.child_id]?.relation ? 'open' : ''}>
                <summary>ほかの子どもとの距離状態・関連度スコア</summary>
                <div class="relation-score-list">
                    ${relationRows || '<p class="ml-empty">比較できる子どもはいません</p>'}
                </div>
            </details>
            <details class="baseline-details" ${state.mlDetailOpenStates[child.child_id]?.baseline ? 'open' : ''}>
                <summary>この子の普段のステータス（基準値）</summary>
                ${behavior ? `
                    <div class="baseline-grid ${staleClass(behaviorIsStale)}">
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
    grid.querySelectorAll('[data-student-card]').forEach((card) => {
        const previous = previousPositions.get(Number(card.dataset.studentCard));
        if (!previous) return;
        const current = card.getBoundingClientRect();
        const deltaX = previous.left - current.left;
        const deltaY = previous.top - current.top;
        if (Math.abs(deltaX) < 1 && Math.abs(deltaY) < 1) return;
        const animation = card.animate([
            { transform: `translate(${deltaX}px, ${deltaY}px)` },
            { transform: 'translate(0, 0)' }
        ], {
            duration: 900,
            easing: 'cubic-bezier(0.2, 0.7, 0.2, 1)'
        });
        animation.id = 'student-reorder';
    });
    ensureSignageAutoScroll();
    renderOpenStudentDetailModal();
}

function stopSignageAutoScroll() {
    if (signageScrollInterval) clearInterval(signageScrollInterval);
    if (signageScrollRetryTimer) clearTimeout(signageScrollRetryTimer);
    signageScrollInterval = 0;
    signageScrollRetryTimer = 0;
}

function scrollSignagePage() {
    if (!document.body.classList.contains('signage-mode')) {
        stopSignageAutoScroll();
        return;
    }
    const grid = document.getElementById('studentGrid');
    const maxScroll = grid.scrollHeight - grid.clientHeight;
    if (maxScroll <= 1) {
        stopSignageAutoScroll();
        signageScrollRetryTimer = setTimeout(() => {
            signageScrollRetryTimer = 0;
            ensureSignageAutoScroll();
        }, 250);
        return;
    }

    if (Date.now() >= signageScrollPauseUntil) {
        grid.scrollTop += signageScrollDirection > 0 ? 1 : -12;
        if (signageScrollDirection > 0 && grid.scrollTop >= maxScroll - 1) {
            grid.scrollTop = maxScroll;
            signageScrollDirection = -1;
        } else if (signageScrollDirection < 0 && grid.scrollTop <= 0) {
            grid.scrollTop = 0;
            signageScrollDirection = 1;
            signageScrollPauseUntil = Date.now() + 1000;
        }
    }
}

function ensureSignageAutoScroll() {
    if (!document.body.classList.contains('signage-mode') || signageScrollInterval) return;
    if (signageScrollRetryTimer) clearTimeout(signageScrollRetryTimer);
    signageScrollRetryTimer = 0;

    const grid = document.getElementById('studentGrid');
    if (grid.scrollHeight - grid.clientHeight <= 1) {
        signageScrollRetryTimer = setTimeout(() => {
            signageScrollRetryTimer = 0;
            ensureSignageAutoScroll();
        }, 250);
        return;
    }
    signageScrollInterval = setInterval(scrollSignagePage, 50);
}

function setSignageMode(enabled, syncFullscreen = true) {
    document.body.classList.toggle('signage-mode', enabled);
    document.getElementById('signageToggleButton').setAttribute('aria-pressed', String(enabled));
    document.getElementById('signageToggleButton').textContent =
        enabled ? '通常表示に戻す' : 'サイネージ表示';
    document.getElementById('signageExitButton').hidden = !enabled;

    if (syncFullscreen && enabled && !document.fullscreenElement) {
        document.documentElement.requestFullscreen?.().catch((error) => {
            console.info('[ui] fullscreen unavailable; using signage view', error);
        });
    } else if (syncFullscreen && !enabled && document.fullscreenElement) {
        document.exitFullscreen?.().catch((error) => {
            console.info('[ui] could not exit fullscreen', error);
        });
    }
    if (enabled) {
        const grid = document.getElementById('studentGrid');
        grid.scrollTop = 0;
        signageScrollDirection = 1;
        signageScrollPauseUntil = 0;
        setTimeout(() => {
            if (document.body.classList.contains('signage-mode')) ensureSignageAutoScroll();
        }, 0);
    } else {
        stopSignageAutoScroll();
    }
}

function renderStudentMlProgress(childId) {
    const progress = state.dataFreshness.mlProgress?.[childId];
    if (!progress) return '';

    const receivedRows = Math.max(0, Number(progress.received_rows) || 0);
    const requiredRows = Math.max(1, Number(progress.required_rows) || 6000);
    const percentage = Math.min(100, receivedRows / requiredRows * 100);
    const remainingRows = Math.max(0, requiredRows - receivedRows);
    const remainingMinutes = remainingRows / 600  + 0.5; // データの受信には30秒の遅延を考慮

    return `
        <div class="student-ml-progress">
            <div class="student-ml-progress-heading">
                <span>次のステータスの更新までのデータ蓄積量</span>
                <strong>${percentage.toFixed(1)}%（残り約${remainingMinutes.toFixed(1)}分）</strong>
            </div>
            <div class="student-ml-progress-track" role="progressbar" aria-label="次のステータスの更新まで" aria-valuemin="0" aria-valuemax="${requiredRows}" aria-valuenow="${Math.min(receivedRows, requiredRows)}">
                <div class="student-ml-progress-bar" style="width: ${percentage}%"></div>
            </div>
        </div>`;
}

function renderOpenStudentDetailModal() {
    const childId = openStudentDetailChildId;
    if (childId === null) return;

    const modal = document.getElementById('studentDetailModal');
    if (!modal || modal.classList.contains('is-hidden')) return;

    const child = state.children.find((item) => item.child_id === childId);
    const card = document.querySelector(`[data-student-card="${childId}"]`);
    if (!child || !card) return;

    document.getElementById('studentDetailTitle').textContent =
        `${child.name || `子ども${childId}`}の詳細`;
    document.getElementById('studentDetailContent').innerHTML = `
        <div class="student-detail-summary">
            <strong>${escapeHtml(child.name || `子ども${childId}`)}</strong>
            <span>${escapeHtml(state.nearestNames[childId] ? `最も近くにいる人：${state.nearestNames[childId]}` : '近くにいる人：データなし')}</span>
            <span>歩数：${(state.steps[childId] || 0).toLocaleString()}</span>
        </div>
        ${card.querySelector('.device-status')?.outerHTML || ''}
        ${card.querySelector('.student-status')?.outerHTML || ''}
        ${renderStudentMlProgress(childId)}
        ${card.querySelector('.ml-summary')?.outerHTML || ''}`;
}

function openStudentDetailModal(childId) {
    openStudentDetailChildId = childId;
    openModal('studentDetailModal');
    renderOpenStudentDetailModal();
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
            ? `<span>${index + 1}.</span><strong>${escapeHtml(entry.name || `子ども${entry.child_id}`)}</strong>`
            : `<span>${index + 1}.</span><strong>-</strong>`;
    });
}

function renderModelAnomalyWarnings() {
    const panel = document.getElementById('modelAnomalyPanel');
    const list = document.getElementById('modelAnomalyList');
    const items = state.children.flatMap((child) => {
        const anomaly = state.mlAnomalies[child.child_id];
        if (anomaly?.warning !== true) return [];
        const reasons = Object.entries(anomaly.comparisons || {})
            .filter(([, comparison]) => comparison.warning === true)
            .map(([feature, comparison]) =>
                `<li>${escapeHtml(formatAnomalyChange(feature, comparison))}</li>`
            );
        if (!reasons.length) return [];
        return [`<li class="model-anomaly-item">
            <button class="model-anomaly-child-link" type="button" data-anomaly-child="${child.child_id}">${escapeHtml(child.name || `子ども${child.child_id}`)}</button>
            <ul>${reasons.join('')}</ul>
        </li>`];
    });
    list.innerHTML = items.length
        ? items.join('')
        : '<li class="model-anomaly-clear">現在、警告はありません。</li>';
    document.getElementById('modelAnomalyCount').textContent = items.length
        ? `${items.length}人に異常を検知`
        : '警告なし';
    panel.hidden = false;
    panel.classList.toggle('is-clear', items.length === 0);
}

// 警告を児童IDごとに最新1件へ絞り、現在のクラスの警告だけを表示する。
function renderWarnings(warnings) {
    const warningList = document.getElementById('warningList');
    if (!warningList) return;
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

// クラス一覧を管理モーダルへ描画する。
async function refreshClassList() {
    const result = await apiRequest('/api/classes');
    document.getElementById('classList').innerHTML = (result.classes || []).map((item) => `
        <div class="class-row"><span>${escapeHtml(item.name)}（${item.child_count}人）</span>
        <div class="class-actions">
            <button type="button" data-rename-class="${item.class_id}">名前変更</button>
            <button type="button" class="danger-button" data-delete-class="${item.class_id}" data-class-name="${escapeHtml(item.name)}" data-child-count="${item.child_count}">削除</button>
        </div></div>`).join('') || '<p class="class-empty">クラスが登録されていません。</p>';
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
            const relationIsStale = relation ? isMlResultStale(relation.date) : false;

            rows.push(`
                <div class="relation-pair${staleClass(relationIsStale)}">
                    <strong>${escapeHtml(child1.name)} ↔ ${escapeHtml(child2.name)}</strong>
                    <span>距離状態: ${relation ? escapeHtml(relation.evaluated) : '未算出'}</span>
                    <span>信頼度: ${relation ? formatConfidence(relation.confidence) : '-'}</span>
                    <span>関連度: ${relation ? formatMlNumber(relation.score) : '-'}</span>
                </div>`);
        }
    }
    graph.innerHTML = rows.length ? rows.join('') : '<span>比較できる子どものデータがありません</span>';
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

function shortenNetworkName(name, maxLength = 7) {
    const chars = [...String(name || '')];

    if (chars.length <= maxLength) {
        return chars.join('');
    }

    return `${chars.slice(0, maxLength).join('')}…`;
}

// 児童間の関係ネットワーク図を描画する。（重み付き無向グラフとして描画）
function renderRelatedNetwork() {
    const container = document.getElementById('relatedNetworkGraph');
    const detail = document.getElementById('networkEdgeDetail');
    const children = state.children;

    if (children.length < 2) {
        container.innerHTML = '<p>関係を表示できる子どもの数が足りません。</p>';
        return;
    }

    const width = 1200;
    const height = 460;

    const centerX = width / 2;
    const centerY = height / 2;

    const radiusX = width * 0.43;
    const radiusY = height * 0.39;

    let nodeRadius = 34;
    let nodeFontSize = 14;
    let maxNameLength = 7;

    if (children.length > 16) {
        nodeRadius = 23;
        nodeFontSize = 10;
        maxNameLength = 5;
    } else if (children.length > 12) {
        nodeRadius = 26;
        nodeFontSize = 11;
        maxNameLength = 6;
    } else if (children.length > 8) {
        nodeRadius = 30;
        nodeFontSize = 12;
        maxNameLength = 6;
    }

    const nodes = children.map((child, index) => {
        const angle = (Math.PI * 2 * index / children.length) - Math.PI / 2;
        return {
            ...child,
            x: centerX + Math.cos(angle) * radiusX,
            y: centerY + Math.sin(angle) * radiusY
        };
    });

    const denseGraph = nodes.length >= 13;
    const veryDenseGraph = nodes.length >= 18;

    let edges = '';

    for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
            const node1 = nodes[i];
            const node2 = nodes[j];

            const relation = state.mlRelations[relationKey(node1.child_id, node2.child_id)];
            if (!relation) continue;

            const score = Number(relation.score);
            if (!Number.isFinite(score)) continue;

            // 関連度スコアが0以下なら線は描画しない
            if (score <= 0) continue;

            const normalizedScore = Math.max(0, Math.min(1, score));

            // 人数が多い場合は最大線幅を抑える
            const maxExtraWidth = veryDenseGraph ? 4 : denseGraph ? 6 : 12;

            // 線幅を決める
            const strokeWidth = 0.8 + Math.pow(normalizedScore, 1.7) * maxExtraWidth;

            // 線の色を決める
            const strokeColor = relationEdgeColor(normalizedScore);

            const baseOpacity = veryDenseGraph ? 0.12 : denseGraph ? 0.18 : 0.3;

            const opacityRange = veryDenseGraph ? 0.30 : denseGraph ? 0.42 : 0.6;

            const edgeId = `network-edge-${node1.child_id}-${node2.child_id}`;

            edges += `
                <!-- クリック判定専用：透明で太い線 -->
                <line
                    class="network-edge-hit"
                    data-network-edge
                    data-edge-id="${edgeId}"

                    data-child1="${node1.child_id}"
                    data-child2="${node2.child_id}"

                    data-name1="${escapeHtml(node1.name)}"
                    data-name2="${escapeHtml(node2.name)}"

                    data-score="${score}"

                    data-distance="${escapeHtml(relation.evaluated || '')}"
                    data-confidence="${relation.confidence ?? ''}"

                    x1="${node1.x}"
                    y1="${node1.y}"
                    x2="${node2.x}"
                    y2="${node2.y}"

                    stroke="transparent"
                    stroke-width="24"
                />

                <!-- 実際に見える線 -->
                <line
                    class="network-edge"
                    data-network-visible-edge
                    data-edge-id="${edgeId}"

                    data-child1="${node1.child_id}"
                    data-child2="${node2.child_id}"

                    x1="${node1.x}"
                    y1="${node1.y}"
                    x2="${node2.x}"
                    y2="${node2.y}"

                    stroke="${strokeColor}"
                    stroke-width="${strokeWidth}"

                    stroke-opacity="${baseOpacity + normalizedScore * opacityRange}"
                    
                    pointer-events="none"
                />
            `;
        }
    }

    const nodeHtml = nodes.map((node) => `
        <g class="network-node">
            <circle
                cx="${node.x}"
                cy="${node.y}"
                r="34">
            </circle>

            <text
                x="${node.x}"
                y="${node.y}"
                text-anchor="middle"
                dominant-baseline="middle">
                ${escapeHtml(node.name)}
            </text>
        </g>
    `).join('');

    container.innerHTML = `
        <svg
            class="network-svg"
            viewBox="0 0 ${width} ${height}"
            role="img"
            aria-label="子ども同士の関係ネットワーク図">

            ${edges}
            ${nodeHtml}

        </svg>
    `;

    detail.innerHTML = `
        <strong>関係を選択してください</strong>
        <span>グラフ内の線をクリックしてそのステータスを確認できます。</span>
    `;

    container
        .querySelectorAll('[data-network-edge]')
        .forEach((edge) => {

            edge.addEventListener('click', () => {

                container
                    .querySelectorAll('[data-network-edge]')
                    .forEach((other) => {
                        other.classList.remove('is-selected');
                    });

                edge.classList.add('is-selected');

                const score =
                    Number(edge.dataset.score);

                const confidence =
                    Number(edge.dataset.confidence);

                detail.innerHTML = `
                    <strong>
                        ${escapeHtml(edge.dataset.name1)}
                        ↔
                        ${escapeHtml(edge.dataset.name2)}
                    </strong>

                    <span>関連度スコア</span>

                    <span class="network-edge-score">
                        ${formatMlNumber(score, 3)}
                    </span>

                    <span>0から1までの値です。1に近いほど関連度が高いと推定されます。</span>
                `;
            });
        });
}

async function openRelatedNetworkModal() {
    openModal('relatedNetworkModal');

    const graph = document.getElementById('relatedNetworkGraph');
    graph.innerHTML = '<p>データを読み込み中...</p>';

    try {
        await loadMlResults(true);
        renderRelatedNetwork();
    } catch (error) {
        console.error(
            '[ui] related network failed',
            error
        );

        graph.innerHTML = '<p>関係ネットワーク図を生成できませんでした。</p>';
    }
}

function relationEdgeColor(score) {
    const value = Math.max(0, Math.min(1, Number(score)));

    if (value >= 0.8) return '#b71c1c';
    if (value >= 0.6) return '#e65100';
    if (value >= 0.4) return '#d49b00';
    if (value >= 0.2) return '#9a7777';

    return '#c9baba';
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
    const children = childrenResult.children || [];
    const classNames = new Map(classes.map((item) => [item.class_id, item.name]));
    document.getElementById('studentManageCount').textContent = `${children.length}人`;
    document.getElementById('studentManageList').innerHTML = children.length ? children.map((child) => {
        const isTeacher = isTeacherFlag(child.child_id);
        return `<tr class="student-manage-row ${isTeacher ? 'is-teacher' : ''}" data-manage-row="${child.child_id}">
            <td>${child.child_id}</td>
            <td class="student-manage-name">${escapeHtml(child.name)}</td>
            <td><select data-manage-class="${child.child_id}" aria-label="${escapeHtml(child.name)}の所属クラス">
                <option value="">未所属</option>
                ${classes.map((item) => `<option value="${item.class_id}" ${item.class_id === child.class_id ? 'selected' : ''}>${escapeHtml(item.name)}</option>`).join('')}
            </select></td>
            <td><label class="teacher-checkbox">
                <input type="checkbox" data-manage-teacher="${child.child_id}" ${isTeacher ? 'checked' : ''}>
                先生用
            </label></td>
        </tr>`;
    }).join('') : '<tr><td colspan="4">登録されている子どもはいません</td></tr>';
    document.getElementById('studentDeleteList').innerHTML = children.length ? children.map((child) => `
        <tr>
            <td><input type="checkbox" data-delete-child="${child.child_id}" aria-label="${escapeHtml(child.name)}を削除対象にする"></td>
            <td>${child.child_id}</td>
            <td>${escapeHtml(child.name)}</td>
            <td>${escapeHtml(classNames.get(child.class_id) || '未所属')}</td>
        </tr>`).join('') : '<tr><td colspan="4">削除できる子どもはいません</td></tr>';
    document.getElementById('selectAllStudentDelete').checked = false;
    updateStudentDeleteSelection();
}

function updateStudentDeleteSelection() {
    const checkboxes = [...document.querySelectorAll('[data-delete-child]')];
    const selectedCount = checkboxes.filter((checkbox) => checkbox.checked).length;
    const selectAll = document.getElementById('selectAllStudentDelete');
    selectAll.checked = checkboxes.length > 0 && selectedCount === checkboxes.length;
    selectAll.indeterminate = selectedCount > 0 && selectedCount < checkboxes.length;
    document.getElementById('studentDeleteSelectionCount').textContent = `${selectedCount}人選択中`;
    document.getElementById('deleteSelectedChildrenButton').disabled = selectedCount === 0;
}

async function deleteSelectedChildren() {
    const childIds = [...document.querySelectorAll('[data-delete-child]:checked')]
        .map((checkbox) => Number(checkbox.dataset.deleteChild));
    if (!childIds.length) return;
    if (!confirm(`選択した${childIds.length}人の子どもと関連データを削除します。よろしいですか？`)) return;

    const button = document.getElementById('deleteSelectedChildrenButton');
    button.disabled = true;
    setMessage('studentDeleteMessage', '削除中...');
    try {
        const result = await apiRequest('/api/children', {
            method: 'DELETE',
            body: JSON.stringify({ child_ids: childIds })
        });
        childIds.forEach((childId) => {
            state.teacherFlags.delete(childId);
            delete state.mlBehavior[childId];
            delete state.mlAnomalies[childId];
            delete state.mlDetailOpenStates[childId];
        });
        localStorage.setItem('sukusuteTeacherFlags', JSON.stringify([...state.teacherFlags]));
        await Promise.all([loadDashboard(), refreshStudentManageList()]);
        setMessage('studentManageMessage', result.msg || '子どもを削除しました。');
        openModal('studentManageModal');
    } catch (error) {
        setMessage('studentDeleteMessage', error.message);
        button.disabled = false;
    }
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
    openStudentDetailChildId = null;
}

// 現在ログイン中のユーザー名を初期値にして削除画面を開く。
function openAccountDeleteModal() {
    document.getElementById('deleteUsernameDisplay').textContent =
        state.teacher?.username || '';

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

async function submitLogin(event) {
    event.preventDefault();
    const button = document.getElementById('loginButton');
    if (button.disabled) return;
    button.disabled = true;
    setMessage('loginMessage', '');
    try {
        await login(document.getElementById('loginUsername').value, document.getElementById('loginPassword').value);
    } catch (error) {
        setMessage('loginMessage', error.message);
    } finally {
        button.disabled = false;
    }
}

document.getElementById('loginForm').addEventListener('submit', submitLogin);
document.getElementById('loginButton').addEventListener('click', submitLogin);

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

// 未ログイン時にはメニューを開かせない
document.getElementById('menuButton').addEventListener('click', () => {
    if (!state.token) {
        closeMenu();
        return;
    }

    const menuPanel = document.getElementById('menuPanel');
    menuPanel.classList.add('is-open');
    menuPanel.setAttribute('aria-hidden', 'false');
});

document.getElementById('closeMenuButton').addEventListener('click', closeMenu);
document.getElementById('signageToggleButton').addEventListener('click', () => {
    setSignageMode(!document.body.classList.contains('signage-mode'));
});
document.getElementById('signageExitButton').addEventListener('click', () => setSignageMode(false));
document.getElementById('modelAnomalyList').addEventListener('click', (event) => {
    const button = event.target.closest('[data-anomaly-child]');
    if (button) openStudentDetailModal(Number(button.dataset.anomalyChild));
});
document.addEventListener('fullscreenchange', () => {
    if (!document.fullscreenElement && document.body.classList.contains('signage-mode')) {
        setSignageMode(false, false);
    } else {
        ensureSignageAutoScroll();
    }
});
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && document.body.classList.contains('signage-mode')) {
        setSignageMode(false);
    }
});
window.addEventListener('resize', ensureSignageAutoScroll);
document.querySelectorAll('[data-display-mode]').forEach((button) => button.addEventListener('click', () => {
    setDisplayMode(button.dataset.displayMode);
}));
document.querySelectorAll('[data-close-modal]').forEach((button) => button.addEventListener('click', closeModal));
document.querySelector('[data-action="display-settings"]').addEventListener('click', (event) => {
    const submenu = document.getElementById('displayModeMenu');
    const isOpen = submenu.classList.toggle('is-hidden') === false;
    event.currentTarget.setAttribute('aria-expanded', String(isOpen));
});
document.querySelector('[data-action="display-horizontal"]').addEventListener('click', () => {
    setDisplayMode('horizontal');
    closeMenu();
});
document.querySelector('[data-action="display-square"]').addEventListener('click', () => {
    setDisplayMode('square');
    closeMenu();
});
document.querySelector('[data-action="class"]').addEventListener('click', () => { document.getElementById('menuPanel').classList.remove('is-open'); openClassModal(); });
document.querySelector('[data-action="student-manage"]').addEventListener('click', () => { document.getElementById('menuPanel').classList.remove('is-open'); openStudentManageModal(); });
document.querySelector('[data-action="relation"]').addEventListener('click', () => { document.getElementById('menuPanel').classList.remove('is-open'); openRelationModal(); });
document.querySelector('[data-action="related-network"]').addEventListener('click', () => { closeMenu(); openRelatedNetworkModal(); });

document.querySelector('[data-action="refresh"]').addEventListener('click', () => {
    document.getElementById('menuPanel').classList.remove('is-open');
    console.info('[ui] manual refresh clicked');
    loadDashboard();
});

document.querySelector('[data-action="account-delete"]').addEventListener('click', () => { document.getElementById('menuPanel').classList.remove('is-open'); openAccountDeleteModal(); });

document.querySelector('[data-action="config"]').addEventListener(
    'click',
    async () => {
        try {
            await openConfigModal();
        } catch (error) {
            console.error(error);
            alert(`コンフィグの取得に失敗しました: ${error.message}`);
        }
    }
);

document.querySelector('[data-action="logout"]').addEventListener('click', async () => {
    try {
        await apiRequest('/api/auth/logout', { method: 'POST' });
    } catch (error) {
        console.error(error);
    }

    closeMenu();

    localStorage.removeItem('sukusuteToken');
    state.token = null;
    state.teacher = null;

    showLogin();
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
    const deleteButton = event.target.closest('[data-delete-class]');
    if (deleteButton) {
        const classId = Number(deleteButton.dataset.deleteClass);
        const className = deleteButton.dataset.className;
        const childCount = Number(deleteButton.dataset.childCount);
        const unassigned = childCount ? `所属している${childCount}人は未所属になります。` : '所属している子どもはいません。';
        if (!confirm(`クラス「${className}」を削除しますか？\n${unassigned}\n子どもの計測データは削除されません。`)) return;
        try {
            const result = await apiRequest(`/api/classes/${classId}`, { method: 'DELETE' });
            if (state.selectedClassId === classId) state.selectedClassId = null;
            await loadClasses();
            await refreshClassList();
            setMessage('classMessage', result.msg || 'クラスを削除しました。');
        } catch (error) {
            setMessage('classMessage', error.message);
        }
        return;
    }
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
document.getElementById('configForm').addEventListener(
    'submit',
    async (event) => {
        event.preventDefault();
        setMessage('configMessage', '');

        const activityHours = Number(document.getElementById('configActivityMaxHours').value);
        const activityMinutes = Number(document.getElementById('configActivityMaxMinutes').value);
        const activityMaxDataMinutes = activityHours * 60 + activityMinutes;

        if (activityMaxDataMinutes < 1) {
            setMessage(
                'configMessage',
                '活動量推論に使用する過去データ量は1分以上にしてください。'
            );
            return;
        }

        const hours = Number(document.getElementById('configBaselineMinHours').value);
        const minutes = Number(document.getElementById('configBaselineMinMinutes').value);
        const baselineMinDataMinutes = hours * 60 + minutes;

        const body = {
            activity_max_data_minutes:
                activityMaxDataMinutes,

            anomaly_threshold_percent: Number(
                document.getElementById(
                    'configAnomalyThreshold'
                ).value
            ),

            baseline_min_data_minutes:
                baselineMinDataMinutes,

            baseline_max_days: Number(
                document.getElementById(
                    'configBaselineMaxDays'
                ).value
            ),

            relatedness_max_history: Number(
                document.getElementById(
                    'configRelatednessMaxHistory'
                ).value
            ),
        };

        try {
            await apiRequest(
                '/api/ml/config',
                {
                    method: 'PATCH',
                    body: JSON.stringify(body),
                }
            );

            setMessage(
                'configMessage',
                '設定を保存しました。'
            );

            // ML結果の再取得を促す
            state.mlUpdatedAt = 0;

        } catch (error) {
            setMessage(
                'configMessage',
                error.message
            );
        }
    }
);
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
document.getElementById('openStudentDeleteModalButton').addEventListener('click', () => {
    setMessage('studentDeleteMessage', '');
    updateStudentDeleteSelection();
    openModal('studentDeleteModal');
});
document.getElementById('studentDeleteList').addEventListener('change', updateStudentDeleteSelection);
document.getElementById('selectAllStudentDelete').addEventListener('change', (event) => {
    document.querySelectorAll('[data-delete-child]').forEach((checkbox) => {
        checkbox.checked = event.target.checked;
    });
    updateStudentDeleteSelection();
});
document.getElementById('deleteSelectedChildrenButton').addEventListener('click', deleteSelectedChildren);
document.getElementById('accountDeleteForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!confirm('アカウントを削除しますか？この操作は取り消せません。')) return;
    try {
        await apiRequest('/api/auth/account', {
            method: 'DELETE',
            body: JSON.stringify({
                username: state.teacher?.username || '',
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
}, 10000);