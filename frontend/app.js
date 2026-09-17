const state = {
    token: localStorage.getItem('sukusuteToken'),
    teacher: null,
    classes: [],
    selectedClassId: null,
    children: [],
    steps: {},
    selectedDate: new Date()
};

// 画面表示に使う歩数ルール。カードと警告で同じ基準を使う。
const STEP_WARNING_THRESHOLD = 3000;
const WARNING_DECREASE_PERCENT = 60;
const NORMAL_INCREASE_PERCENT = 20;

let refreshTimer = null;
let refreshInProgress = false;

// ===== API通信と認証状態 =====

async function apiRequest(url, options = {}) {
    console.info('[ui] API request', options.method || 'GET', url);
    const headers = { ...(options.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    if (options.body) headers['Content-Type'] = 'application/json';
    const response = await fetch(url, { ...options, headers });
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && state.token) {
        localStorage.removeItem('sukusuteToken');
        state.token = null;
        showLogin();
        throw new Error('ログインの有効期限が切れています。もう一度ログインしてください。');
    }
    if (!response.ok) {
        console.error('[ui] API error', response.status, url, body);
        throw new Error(body.detail || `HTTP ${response.status}`);
    }
    console.info('[ui] API response', response.status, url);
    return body;
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
    selector.innerHTML = '<option value="">全員のようす</option>' + state.classes
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
        const stats = await apiRequest(`/api/stats/today?${dateQuery(state.selectedDate)}`);
        state.steps = {};
        for (const item of stats.student_ranking || []) state.steps[item.child_id] = item.steps || 0;
        renderStudents();
        renderRanking();
        renderWarnings(stats.warnings || []);
        setMessage('refreshMessage', `最終更新 ${new Date().toLocaleTimeString()}`);
        console.info('[ui] dashboard refresh completed', {
            children: state.children.length,
            steps: Object.keys(state.steps).length
        });
    } catch (error) {
        setMessage('refreshMessage', error.message);
        console.error('[ui] dashboard refresh failed', error);
    } finally {
        refreshInProgress = false;
    }
}

// 児童を歩数順に並べ、歩数カードをHTMLへ描画する。
function renderStudents() {
    const grid = document.getElementById('studentGrid');
    if (!state.children.length) {
        grid.innerHTML = '<div class="loading">このクラスに児童データがありません</div>';
        return;
    }
    const sorted = [...state.children].sort((a, b) => (state.steps[b.child_id] || 0) - (state.steps[a.child_id] || 0));
    grid.innerHTML = sorted.map((child) => {
        const steps = state.steps[child.child_id] || 0;
        const warning = steps > 0 && steps < STEP_WARNING_THRESHOLD;
        return `<article class="student-card">
            <div class="student-name">${escapeHtml(child.name || `児童${child.child_id}`)}</div>
            <div class="student-steps">歩数：<strong>${steps.toLocaleString()}</strong></div>
            <div class="student-status ${warning ? 'warning' : 'normal'}">
                ${warning ? `活動量が<strong>${WARNING_DECREASE_PERCENT}%</strong>低下` : `通常の活動量より${NORMAL_INCREASE_PERCENT}%増加`}
            </div>
        </article>`;
    }).join('');
}

// 現在表示中の児童から歩数上位5名をランキングへ描画する。
function renderRanking() {
    const ranking = [...state.children].sort((a, b) => (state.steps[b.child_id] || 0) - (state.steps[a.child_id] || 0)).slice(0, 5);
    document.querySelectorAll('#rankingList li').forEach((item, index) => {
        const child = ranking[index];
        item.innerHTML = child
            ? `<span>${index + 1}.</span><strong>${escapeHtml(child.name || `児童${child.child_id}`)}</strong>`
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

// 現在の児童を関係図モーダルへノードとして描画する。
async function openRelationModal() {
    const graph = document.getElementById('relationGraph');
    graph.innerHTML = state.children.length
        ? state.children.map((child) => `<span class="relation-node">${escapeHtml(child.name)}</span>`).join('<span aria-hidden="true">↔</span>')
        : '<span>児童データがありません</span>';
    openModal('relationModal');
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
