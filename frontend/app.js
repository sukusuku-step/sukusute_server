const state = {
    token: localStorage.getItem('sukusuteToken'),
    teacher: null,
    classes: [],
    selectedClassId: null,
    children: [],
    steps: {},
    selectedDate: new Date()
};

async function apiRequest(url, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    if (options.body) headers['Content-Type'] = 'application/json';
    const response = await fetch(url, { ...options, headers });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
    return body;
}

function dateQuery(date) {
    return `year=${date.getFullYear()}&month=${date.getMonth() + 1}&day=${date.getDate()}`;
}

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

function showApp() {
    document.getElementById('loginView').classList.add('is-hidden');
    document.getElementById('appView').classList.remove('is-hidden');
}

function showLogin() {
    document.getElementById('loginView').classList.remove('is-hidden');
    document.getElementById('appView').classList.add('is-hidden');
}

async function loadClasses() {
    const result = await apiRequest('/api/classes');
    state.classes = result.classes || [];
    const selector = document.getElementById('classSelector');
    selector.innerHTML = state.classes.length
        ? state.classes.map((item) => `<option value="${item.class_id}">${escapeHtml(item.name)}　のようす</option>`).join('')
        : '<option value="">クラスを追加してください</option>';
    if (!state.selectedClassId && state.classes.length) {
        state.selectedClassId = state.classes[0].class_id;
    }
    selector.value = state.selectedClassId || '';
    await loadDashboard();
}

async function loadDashboard() {
    const classQuery = state.selectedClassId ? `?class_id=${state.selectedClassId}` : '';
    const children = await apiRequest(`/api/children${classQuery}`);
    state.children = children.children || [];
    const stats = await apiRequest(`/api/stats/today?${dateQuery(state.selectedDate)}`);
    state.steps = {};
    for (const item of stats.student_ranking || []) state.steps[item.child_id] = item.steps || 0;
    renderStudents();
    renderRanking();
}

function renderStudents() {
    const grid = document.getElementById('studentGrid');
    if (!state.children.length) {
        grid.innerHTML = '<div class="loading">このクラスに児童データがありません</div>';
        return;
    }
    const sorted = [...state.children].sort((a, b) => (state.steps[b.child_id] || 0) - (state.steps[a.child_id] || 0));
    grid.innerHTML = sorted.map((child) => {
        const steps = state.steps[child.child_id] || 0;
        const warning = steps > 0 && steps < 3000;
        return `<article class="student-card">
            <div class="student-name">${escapeHtml(child.name || `児童${child.child_id}`)}</div>
            <div class="student-steps">歩数：<strong>${steps.toLocaleString()}</strong></div>
            <div class="student-status ${warning ? 'warning' : 'normal'}">
                ${warning ? '活動量が<strong>60%</strong>低下' : '通常の活動量より２０％増加'}
            </div>
        </article>`;
    }).join('');
}

function renderRanking() {
    const ranking = [...state.children].sort((a, b) => (state.steps[b.child_id] || 0) - (state.steps[a.child_id] || 0)).slice(0, 5);
    document.querySelectorAll('#rankingList li').forEach((item, index) => {
        const child = ranking[index];
        item.innerHTML = child
            ? `<span>${index + 1}.</span><strong>${escapeHtml(child.name || `児童${child.child_id}`)}</strong>`
            : `<span>${index + 1}.</span><strong>-</strong>`;
    });
}

async function openClassModal() {
    await refreshClassList();
    openModal('classModal');
}

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

async function openRelationModal() {
    const graph = document.getElementById('relationGraph');
    graph.innerHTML = state.children.length
        ? state.children.map((child) => `<span class="relation-node">${escapeHtml(child.name)}</span>`).join('<span aria-hidden="true">↔</span>')
        : '<span>児童データがありません</span>';
    openModal('relationModal');
}

function openModal(id) {
    document.getElementById('modalLayer').classList.remove('is-hidden');
    document.querySelectorAll('.modal-card').forEach((modal) => modal.classList.add('is-hidden'));
    document.getElementById(id).classList.remove('is-hidden');
}

function closeModal() {
    document.getElementById('modalLayer').classList.add('is-hidden');
}

function setMessage(id, message) {
    document.getElementById(id).textContent = message;
}

function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (character) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    }[character]));
}

function formatDate(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

document.getElementById('loginForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
        await login(document.getElementById('loginUsername').value, document.getElementById('loginPassword').value);
    } catch (error) {
        setMessage('loginMessage', error.message);
    }
});

document.getElementById('registerForm').addEventListener('submit', async (event) => {
    event.preventDefault();
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
document.querySelectorAll('[data-close-modal]').forEach((button) => button.addEventListener('click', closeModal));
document.querySelector('[data-action="class"]').addEventListener('click', () => { document.getElementById('menuPanel').classList.remove('is-open'); openClassModal(); });
document.querySelector('[data-action="relation"]').addEventListener('click', () => { document.getElementById('menuPanel').classList.remove('is-open'); openRelationModal(); });
document.querySelector('[data-action="refresh"]').addEventListener('click', () => { document.getElementById('menuPanel').classList.remove('is-open'); loadDashboard(); });
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
    try {
        await apiRequest('/api/classes', { method: 'POST', body: JSON.stringify({ name: document.getElementById('newClassName').value }) });
        document.getElementById('newClassName').value = '';
        await refreshClassList();
        await loadClasses();
    } catch (error) { alert(error.message); }
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

if (state.token) {
    showApp();
    loadClasses().catch(() => { localStorage.removeItem('sukusuteToken'); state.token = null; showLogin(); });
}
