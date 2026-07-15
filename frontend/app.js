/**
 * すくすてダッシュボード - メインJavaScript
 * 
 * FastAPI サーバと通信して、お子さんのデータを表示します。
 */

const API = "http://localhost:8000";
let curId = null;

// ページ読み込み完了時
document.addEventListener("DOMContentLoaded", function() {
    checkHealth();
    loadChildren();
});

/**
 * サーバのヘルスチェック
 */
async function checkHealth() {
    const dot = document.getElementById("healthDot");
    const text = document.getElementById("healthText");
    try {
        const r = await fetch(API + "/api/health");
        const j = await r.json();
        if (j.status === "ok") {
            dot.className = "health-dot healthy";
            text.textContent = "接続済み";
        } else {
            throw new Error("Invalid response");
        }
    } catch (e) {
        dot.className = "health-dot error";
        text.textContent = "切断";
    }
}

/**
 * 児童一覧を取得
 */
async function loadChildren() {
    const select = document.getElementById("childSelect");
    const loading = document.getElementById("childListLoading");
    loading.style.display = "flex";
    const ids = [];
    
    for (let i = 1; i <= 20; i++) {
        try {
            const r = await fetch(API + "/api/children/" + i);
            if (r.ok) {
                const j = await r.json();
                ids.push(i);
            }
        } catch (e) {
            // 無視
        }
    }
    
    loading.style.display = "none";
    
    if (ids.length === 0) {
        select.innerHTML = "<option>お子さんがいません</option>";
        select.disabled = false;
        return;
    }
    
    select.innerHTML = ids.map(function(id) {
        return "<option value=\"" + id + "\">ID: " + id + "</option>";
    }).join("");
    
    select.disabled = false;
    select.onchange = function() {
        curId = parseInt(this.value);
        loadSelectedChildData();
    };
    
    if (ids.length > 0) {
        select.value = ids[0];
        curId = ids[0];
        loadSelectedChildData();
    }
}

/**
 * 選択された児童のデータを取得
 */
async function loadSelectedChildData() {
    if (!curId) return;
    
    try {
        const r = await fetch(API + "/api/children/" + curId);
        if (!r.ok) throw new Error("Not found");
        const data = await r.json();
        showData(data);
    } catch (e) {
        console.error("Error loading child data:", e);
        showMessage("データを読み込めませんでした", "error");
    }
}

/**
 * 取得したデータを表示
 */
function showData(d) {
    document.getElementById("childDetailCard").style.display = "block";
    document.getElementById("childName").textContent = "ID: " + d.child_id;
    document.getElementById("deviceId").textContent = d.device_id;
    document.getElementById("childId").textContent = d.child_id;
    
    document.getElementById("stepsCard").style.display = "block";
    showSteps(d.singledata);
    
    document.getElementById("distanceCard").style.display = "block";
    showDist(d.distancedata);
}

/**
 * 歩数データをバーチャートで表示
 */
function showSteps(data) {
    const chart = document.getElementById("stepsChart");
    if (!data || !data.length) {
        chart.innerHTML = "<div class='no-data'>データがありません</div>";
        return;
    }
    const recent = data.slice(-14);
    const max = Math.max.apply(null, recent.map(function(d) { return d.steps; })) || 1;
    
    chart.innerHTML = recent.map(function(d) {
        const height = Math.max((d.steps / max) * 140, 4);
        const date = new Date(d.date).toLocaleDateString("ja-JP", {month: "short", day: "numeric"});
        return "<div class='bar-wrapper'>" +
            "<div class='bar-value'>" + d.steps + "</div>" +
            "<div class='bar' style='height:" + height + "px'></div>" +
            "<div class='bar-label'>" + date + "</div>" +
            "</div>";
    }).join("");
}

/**
 * 距離データをリスト表示
 */
function showDist(data) {
    const list = document.getElementById("distanceList");
    if (!data || !data.length) {
        list.innerHTML = "<li class='no-data'>データがありません</li>";
        return;
    }
    const recent = data.slice(-10).reverse();
    
    list.innerHTML = recent.map(function(d) {
        const date = new Date(d.date).toLocaleDateString("ja-JP", {
            month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
        });
        const name = "ID: " + d.with_child;
        return "<li class='distance-item'>" +
            "<div><div class='child-name'>" + name + "</div>" +
            "<div class='distance-date'>" + date + "</div></div>" +
            "<div class='distance-value'>" + d.distance.toFixed(1) + "m</div>" +
            "</li>";
    }).join("");
}

/**
 * ダミーデータを送信
 */
async function sendDummyData() {
    const btn = document.getElementById("dummyDataBtn");
    btn.disabled = true;
    btn.textContent = "作成中...";
    
    try {
        // 新しいお子さんを作成
        const r1 = await fetch(API + "/api/create_debug_child", { method: "POST" });
        const d1 = await r1.json();
        
        if (d1.status !== "ok") {
            throw new Error("Failed to create child");
        }
        
        // 新規お子さんのIDを取得
        const ids = Object.keys(childNames).map(Number);
        const newId = Math.max.apply(null, ids.concat([0])) + 1;
        
        const now = new Date().toISOString();
        
        // 歩数データを送信
        const stepPayload = {
            child_id: newId,
            singledata: {
                date: now,
                steps: Math.floor(Math.random() * 14000) + 1000
            }
        };
        
        const r2 = await fetch(API + "/api/push_data", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(stepPayload)
        });
        const d2 = await r2.json();
        
        if (d2.status !== "ok") {
            throw new Error("Failed to send step data");
        }
        
        // 距離データを送信（既存のお子さんとの距離）
        const existingIds = ids.filter(function(id) { return id !== newId; });
        for (let i = 0; i < Math.min(existingIds.length, 3); i++) {
            const distPayload = {
                child_id: newId,
                distances: [{
                    date: now,
                    with_child: existingIds[i],
                    distance: Math.round((Math.random() * 5 + 0.5) * 100) / 100
                }]
            };
            
            await fetch(API + "/api/push_data", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(distPayload)
            });
        }
        
        showMessage("送信完了！ お子さん " + newId, "success");
        
        // 一覧を更新
        await loadChildren();
        
    } catch (e) {
        console.error("Error sending dummy data:", e);
        showMessage("送信に失敗しました", "error");
    } finally {
        btn.disabled = false;
        btn.textContent = "📊 ダミーデータ送信";
    }
}

/**
 * メッセージを表示
 */
function showMessage(text, type) {
    const msg = document.getElementById("actionMessage");
    msg.textContent = text;
    msg.className = "message " + type;
    msg.style.display = "block";
    setTimeout(function() {
        msg.style.display = "none";
    }, 5000);
}