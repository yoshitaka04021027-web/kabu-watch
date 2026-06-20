"use strict";

// ---------- 小さなユーティリティ ----------
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
const yen = (n) => (n == null ? "—" : Math.round(n).toLocaleString("ja-JP"));
const yen1 = (n) => (n == null ? "—" : Number(n).toLocaleString("ja-JP", { maximumFractionDigits: 1 }));
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// インラインの onclick='...' 属性に値を埋め込むためのエスケープ。
// JSON.stringify はシングルクォート等を残すので、必ず esc() でHTMLエスケープして属性破壊を防ぐ。
const attr = (v) => esc(JSON.stringify(v));

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = "通信エラー";
    try { msg = (await res.json()).error || msg; } catch (e) {}
    throw new Error(msg);
  }
  return res.json();
}

// ---------- 端末内ローカル保存（この端末＝iPhone/PCの中だけに保存。サーバーには残らない）----------
const LS_WATCH = "jsw_watchlist_v1";
const LS_PORT = "jsw_portfolio_v1";
const LS_TAB = "jsw_active_tab_v1";
function lsGet(key, def) { try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : def; } catch (e) { return def; } }
function lsSet(key, val) { try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) {} }
const getWatch = () => lsGet(LS_WATCH, []);
const setWatch = (a) => lsSet(LS_WATCH, a);
const getPort = () => lsGet(LS_PORT, []);
const setPort = (a) => lsSet(LS_PORT, a);
let editingHoldingId = null;

function numVal(v, def = null) {
  if (v == null || v === "") return def;
  const n = Number(v);
  return Number.isFinite(n) ? n : def;
}

function downloadText(filename, text, type = "application/json") {
  const blob = new Blob([text], { type: type + ";charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}

function setBusy(el, busy) {
  if (!el) return;
  el.classList.toggle("is-busy", !!busy);
  el.setAttribute("aria-busy", busy ? "true" : "false");
}

function setButtonLoading(btn, loading, label) {
  if (!btn) return;
  if (loading) {
    btn.dataset.prevHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<i class="ti ti-loader-2 spin"></i><span>${esc(label || "処理中")}</span>`;
  } else {
    btn.disabled = false;
    if (btn.dataset.prevHtml) btn.innerHTML = btn.dataset.prevHtml;
    delete btn.dataset.prevHtml;
  }
}

function emptyState(icon, title, body, actions = "") {
  return `<div class="empty">
    <i class="ti ${icon}"></i>
    <h3>${esc(title)}</h3>
    ${body ? `<p>${esc(body)}</p>` : ""}
    ${actions ? `<div class="empty-actions">${actions}</div>` : ""}
  </div>`;
}

function changeClass(v) { return v == null ? "" : (v >= 0 ? "up" : "down"); }
function changeStr(v) { if (v == null) return "—"; const s = v >= 0 ? "▲+" : "▼"; return s + Math.abs(v).toFixed(2) + "%"; }
function pctStr(v) { return v == null ? "—" : Number(v).toFixed(v >= 10 ? 1 : 2) + "%"; }
function numStr(v, digits = 1) { return v == null ? "—" : Number(v).toFixed(digits); }
function ageStr(sec) {
  if (sec == null) return "";
  if (sec < 60) return "たった今";
  if (sec < 3600) return Math.round(sec / 60) + "分前";
  if (sec < 86400) return Math.round(sec / 3600) + "時間前";
  return Math.round(sec / 86400) + "日前";
}
function dataBadge(it) {
  const cache = it.cache;
  const label = cache === "stale" ? "古いデータ" : cache === "hit" ? "キャッシュ" : "最新取得";
  const age = ageStr(it.cache_age_sec);
  return `<span class="data-badge ${cache === "stale" ? "stale" : ""}">${label}${age ? "・" + age : ""}</span>`;
}

// スパークライン（終値配列からSVGを生成）
function sparkline(values, up) {
  const v = (values || []).filter(x => x != null);
  if (v.length < 2) return "";
  const w = 100, h = 30, min = Math.min(...v), max = Math.max(...v), rng = (max - min) || 1;
  const pts = v.map((x, i) => `${(i / (v.length - 1) * w).toFixed(1)},${(h - (x - min) / rng * h).toFixed(1)}`);
  const stroke = v[v.length - 1] >= v[0] ? "var(--up)" : "var(--down)";
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polyline fill="none" stroke="${stroke}" stroke-width="1.6" points="${pts.join(" ")}" vector-effect="non-scaling-stroke"/>
  </svg>`;
}

// スコアの円グラフゲージ
function gauge(score, tone) {
  if (score == null) return "";
  const r = 26, c = 2 * Math.PI * r, off = c * (1 - score / 100);
  const col = { strong: "#1f9d57", buy: "#37a85f", neutral: "#8a94a6", weak: "#e8870c", bearish: "#e0353b" }[tone] || "#8a94a6";
  return `<div class="gauge"><svg width="64" height="64">
    <circle cx="32" cy="32" r="${r}" fill="none" stroke="var(--surface-2)" stroke-width="7"/>
    <circle cx="32" cy="32" r="${r}" fill="none" stroke="${col}" stroke-width="7" stroke-linecap="round"
      stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}"/>
  </svg><span class="num">${score}</span></div>`;
}

// ---------- タブ切替 ----------
const loaded = {};
function setActiveTab(id, save = true) {
  $$(".tab").forEach(t => t.classList.remove("active"));
  $$(".panel").forEach(p => p.classList.remove("active"));
  $$(".tab").forEach(t => t.setAttribute("aria-selected", t.dataset.tab === id ? "true" : "false"));
  const tab = $(`.tab[data-tab="${id}"]`);
  const panel = $("#panel-" + id);
  if (!tab || !panel) return;
  tab.classList.add("active");
  panel.classList.add("active");
  if (save) lsSet(LS_TAB, id);
  if (id === "news") loadNews();
  if (id === "port") loadPortfolio();
  if (id === "search") loadWatchlist();
  if (id === "learn") renderGlossary();
}
$$(".tab").forEach(tab => tab.addEventListener("click", () => setActiveTab(tab.dataset.tab)));

// ---------- 市況ティッカー ----------
async function loadMarket() {
  try {
    const d = await api("/api/market");
    $("#ticker").innerHTML = d.items.map(it => {
      if (it.error) return `<div class="tk"><span class="lbl">${esc(it.label)}</span><span class="val">取得失敗</span></div>`;
      const cc = changeClass(it.change_pct);
      const val = it.kind === "為替"
        ? (it.price == null ? "—" : Number(it.price).toFixed(2))
        : yen(it.price);
      return `<div class="tk"><span class="lbl">${esc(it.label)}</span>
        <span class="val">${val}</span>
        <span class="chg ${cc}">${changeStr(it.change_pct)}</span></div>`;
    }).join("");
    $("#updated").textContent = "最終更新 " + d.updated;
  } catch (e) {
    $("#ticker").innerHTML = `<span class="lbl">市況の取得に失敗しました</span>`;
  }
}

// ---------- おすすめ銘柄 ----------
let curHorizon = "short";
$$("#horizonSeg .seg").forEach(s => s.addEventListener("click", () => {
  $$("#horizonSeg .seg").forEach(x => x.classList.remove("active"));
  s.classList.add("active");
  curHorizon = s.dataset.h;
  loadReco();
}));
["recoTop", "recoSector", "recoRisk"].forEach(id => {
  const el = $("#" + id);
  if (el) el.addEventListener("change", () => loadReco());
});

async function loadReco(force) {
  const area = $("#recoArea");
  setBusy(area, true);
  area.innerHTML = `<div class="loading"><i class="ti ti-loader-2 spin"></i><div>最新の株価を取得して分析しています…<br><small>初回は少し時間がかかります</small></div></div>`;
  try {
    const wl = getWatch();
    const codes = wl.length ? "&codes=" + encodeURIComponent(wl.join(",")) : "";
    const want = numVal($("#recoTop").value, 12);
    const d = await api(`/api/recommendations?horizon=${curHorizon}&top=50${codes}${force ? "&force=1" : ""}`);
    const items = filterRecoItems(d.items || []).slice(0, want);
    if (!items.length) {
      area.innerHTML = emptyState(
        "ti-adjustments-off",
        "条件に合う銘柄がありません",
        "業種や値動きの条件をゆるめると候補が表示されます。",
        `<button class="btn primary" onclick="resetRecoFilters()"><i class="ti ti-restore"></i>条件をリセット</button>`
      );
      return;
    }
    const meta = [
      `${items.length}件表示`,
      `分析対象 ${d.watchlist_size || 0}銘柄`,
      d.errors && d.errors.length ? `取得失敗 ${d.errors.length}件` : "",
    ].filter(Boolean);
    area.innerHTML = `<div class="result-meta"><span>${meta.map(esc).join("</span><span>")}</span></div><div class="grid">${items.map((it, i) => recoCard(it, i)).join("")}</div>`;
    bindReasons(area);
  } catch (e) {
    area.innerHTML = emptyState(
      "ti-alert-triangle",
      "分析を取得できませんでした",
      e.message,
      `<button class="btn primary" onclick="loadReco()"><i class="ti ti-refresh"></i>再試行</button>`
    );
  } finally {
    setBusy(area, false);
  }
}

function resetRecoFilters() {
  $("#recoTop").value = "12";
  $("#recoSector").value = "";
  $("#recoRisk").value = "";
  loadReco();
}

function filterRecoItems(items) {
  const sector = $("#recoSector").value;
  const risk = $("#recoRisk").value;
  return items.filter(it => {
    if (sector && it.sector !== sector) return false;
    const atr = it.indicators && it.indicators.atr_pct;
    if (risk === "stable" && !(atr != null && atr <= 3.5)) return false;
    if (risk === "active" && !(atr != null && atr >= 3.5)) return false;
    return true;
  });
}

function recoCard(it, i) {
  const ind = it.indicators || {};
  const f = it.fundamentals || {};
  const goodReasons = (it.reasons || []).filter(r => r.type === "good").slice(0, 3);
  const badReasons = (it.reasons || []).filter(r => r.type === "bad").slice(0, 2);
  const reasons = goodReasons.concat(badReasons);
  const cc = changeClass(ind.change_pct);
  return `<div class="card">
    <div class="card-top">
      <div class="rank ${i < 3 ? "top" : ""}">${i + 1}</div>
      <div class="card-name">
        <div class="nm">${esc(it.name)}</div>
        <div class="meta">${esc(it.code)}<span class="sector">${esc(it.sector || "—")}</span></div>
      </div>
      <div class="price-box">
        <div class="px">${yen1(it.price)}<span style="font-size:11px;color:var(--text-3)"> 円</span></div>
        <div class="chg ${cc}">${changeStr(ind.change_pct)}</div>
      </div>
    </div>
    <div class="score-row">
      ${gauge(it.score, it.tone)}
      <div class="score-meta">
        <span class="verdict t-${it.tone}"><i class="ti ti-flame"></i>${esc(it.verdict)}</span>
        <div class="sub">この時間軸での総合スコア（100点満点）</div>
      </div>
    </div>
    <div class="fund-mini">
      <span>PER ${numStr(f.trailing_pe || f.forward_pe)}</span>
      <span>PBR ${numStr(f.price_to_book)}</span>
      <span>配当 ${pctStr(f.dividend_yield_pct)}</span>
      <span>ROE ${pctStr(f.roe_pct)}</span>
    </div>
    <div class="data-row">${dataBadge(it)}${it.fundamentals_error ? '<span class="data-badge stale">財務指標一部未取得</span>' : ''}</div>
    ${sparkline(it.spark)}
    <div class="reasons">
      ${reasons.map(reasonRow).join("") || '<div class="sub" style="color:var(--text-3)">目立ったシグナルはありません</div>'}
    </div>
    <div class="card-foot">
      <button onclick='openDetail(${attr(it.code)})'><i class="ti ti-zoom-in"></i>くわしく見る</button>
      <button onclick='quickAdd(${attr(it.code)}, ${attr(it.name)})'><i class="ti ti-briefcase"></i>マイ株に登録</button>
    </div>
  </div>`;
}

function reasonRow(r) {
  const cls = r.type === "good" ? "good" : "bad";
  const ic = r.type === "good" ? "ti-check" : "ti-alert-triangle";
  return `<div class="reason ${cls}">
    <span class="ic"><i class="ti ${ic}"></i></span>
    <div class="rt"><div class="lab">${esc(r.label)} <i class="ti ti-chevron-down" style="font-size:13px;color:var(--text-3)"></i></div>
    <div class="det">${esc(r.detail)}</div></div>
  </div>`;
}

function bindReasons(root) {
  $$(".reason", root).forEach(r => r.addEventListener("click", () => r.classList.toggle("open")));
}

// ---------- 詳細モーダル ----------
async function openDetail(code) {
  const bg = $("#modalBg"), m = $("#modal");
  openDetail._lastFocus = document.activeElement;
  bg.classList.add("show");
  m.innerHTML = `<div class="modal-body"><div class="loading"><i class="ti ti-loader-2 spin"></i><div>分析中…</div></div></div>`;
  try {
    const s = await api(`/api/stock/${encodeURIComponent(code)}`);
    m.innerHTML = detailHtml(s);
    bindReasons(m);
    const close = $(".modal-head .btn", m);
    if (close) close.focus();
    if (!s.insufficient) loadStockNews(s.code);
  } catch (e) {
    m.innerHTML = `<div class="modal-head"><h3>エラー</h3><button class="btn ghost" onclick="closeModal()"><i class="ti ti-x"></i></button></div><div class="modal-body">${esc(e.message)}</div>`;
  }
}
function closeModal() {
  $("#modalBg").classList.remove("show");
  if (openDetail._lastFocus && document.contains(openDetail._lastFocus)) openDetail._lastFocus.focus();
}
$("#modalBg").addEventListener("click", e => { if (e.target.id === "modalBg") closeModal(); });
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && $("#modalBg").classList.contains("show")) closeModal();
});

function detailHtml(s) {
  if (s.insufficient) {
    return `<div class="modal-head"><h3>${esc(s.name || s.code)}</h3><button class="btn ghost" onclick="closeModal()"><i class="ti ti-x"></i></button></div>
      <div class="modal-body">${emptyState("ti-database-off", "分析に十分なデータがありません", "少し待って更新するか、別の銘柄を確認してください。")}</div>`;
  }
  const ind = s.indicators;
  const f = s.fundamentals || {};
  const horizons = [["short", s.short], ["mid", s.mid], ["long", s.long]];
  const indRows = [
    ["現在値", yen1(s.price) + " 円"],
    ["前日比", changeStr(ind.change_pct)],
    ["RSI（14日）", ind.rsi != null ? ind.rsi.toFixed(0) : "—"],
    ["5日移動平均", yen(ind.sma5)],
    ["25日移動平均", yen(ind.sma25)],
    ["75日移動平均", yen(ind.sma75)],
    ["200日移動平均", yen(ind.sma200)],
    ["52週高値", yen(s.week52_high)],
    ["52週安値", yen(s.week52_low)],
    ["出来高比（5日/25日）", ind.vol_ratio != null ? ind.vol_ratio.toFixed(2) + "倍" : "—"],
  ];
  const fundRows = [
    ["時価総額", f.market_cap_display || "—"],
    ["PER", numStr(f.trailing_pe || f.forward_pe)],
    ["PBR", numStr(f.price_to_book)],
    ["配当利回り", pctStr(f.dividend_yield_pct)],
    ["ROE", pctStr(f.roe_pct)],
    ["売上成長", pctStr(f.revenue_growth_pct)],
    ["利益成長", pctStr(f.earnings_growth_pct)],
    ["Debt/Equity", numStr(f.debt_to_equity)],
  ];
  return `<div class="modal-head"><h3>${esc(s.name)} <span>${esc(s.code)}</span></h3>
    <button class="btn ghost" onclick="closeModal()" aria-label="詳細を閉じる"><i class="ti ti-x"></i></button></div>
  <div class="modal-body">
    <div class="detail-jump">
      <a href="#detail-indicators"><i class="ti ti-chart-line"></i>指標</a>
      <a href="#detail-signals"><i class="ti ti-list-check"></i>理由</a>
      <a href="#detailNews"><i class="ti ti-news"></i>ニュース</a>
    </div>
    <div class="data-quality ${s.cache === "stale" ? "stale" : ""}">
      <i class="ti ti-database"></i>
      <div>
        <b>データ状態：</b>${dataBadge(s)}
        <span>株価 ${esc(s.data_source || "Yahoo Finance")}</span>
        <span>${s.n_days ? esc(String(s.n_days)) + "営業日で分析" : ""}</span>
        ${s.data_error ? `<div class="warn-text">最新取得に失敗したため、保存済みデータで表示しています。</div>` : ""}
        ${s.fundamentals_error ? `<div class="warn-text">財務指標は一部取得できませんでした。</div>` : ""}
      </div>
    </div>
    ${sparkline(s.spark)}
    <div class="metric-grid" id="detail-indicators">
      ${indRows.map(([k, v]) => `<div class="metric-row"><span>${k}</span><b>${v}</b></div>`).join("")}
    </div>
    <h4 class="detail-subhead"><i class="ti ti-building-bank"></i>ファンダメンタル指標</h4>
    <div class="metric-grid">
      ${fundRows.map(([k, v]) => `<div class="metric-row"><span>${k}</span><b>${v}</b></div>`).join("")}
    </div>
    <div id="detail-signals">
    ${horizons.map(([h, d]) => `
      <div class="horizon-block">
        <div class="horizon-head">
          ${gauge(d.score, d.tone)}
          <div><b>${esc(d.label)}</b>（${esc(d.horizon)}）<br><span class="verdict t-${d.tone}">${esc(d.verdict)}</span></div>
        </div>
        <div class="reasons compact">
          ${(d.reasons || []).filter(r => r.active).map(reasonRow).join("") || '<div class="sub" style="color:var(--text-3)">この時間軸で目立ったシグナルはありません</div>'}
        </div>
      </div>`).join("")}
    </div>
    <div class="news-related" id="detailNews">
      <h4><i class="ti ti-news"></i>関連ニュース</h4>
      <div class="sub" style="color:var(--text-3)">読み込み中…</div>
    </div>
    <div class="modal-actions">
      <button class="btn primary" onclick='quickAdd(${attr(s.code)}, ${attr(s.name)})'><i class="ti ti-briefcase"></i>マイ株に登録</button>
      <button class="btn" onclick='addWatch(${attr(s.code)})'><i class="ti ti-eye-plus"></i>ウォッチリストに追加</button>
    </div>
  </div>`;
}

// ---------- ポートフォリオ ----------
async function loadPortfolio(force) {
  const area = $("#pfArea");
  const holdings = getPort();
  if (!holdings.length) {
    renderSummary(emptyTotals());
    area.innerHTML = emptyState(
      "ti-briefcase",
      "保有銘柄はまだありません",
      "買った株を登録すると、損益と売却検討サインを毎日チェックできます。",
      `<button class="btn primary" onclick="focusPortfolioForm()"><i class="ti ti-circle-plus"></i>保有銘柄を登録</button>`
    );
    return;
  }
  setBusy(area, true);
  area.innerHTML = `<div class="loading"><i class="ti ti-loader-2 spin"></i><div>保有銘柄を評価しています…</div></div>`;
  try {
    const d = await api("/api/portfolio/evaluate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ holdings, force: !!force }),
    });
    renderSummary(d.totals);
    area.innerHTML = d.items.map(holdingHtml).join("");
    bindReasons(area);
  } catch (e) {
    area.innerHTML = emptyState("ti-alert-triangle", "保有銘柄を評価できませんでした", e.message);
  } finally {
    setBusy(area, false);
  }
}

function focusPortfolioForm() {
  $("#pfCode").focus();
  $("#pfCode").scrollIntoView({ behavior: "smooth", block: "center" });
}

function emptyTotals() { return { count: 0, cost: 0, value: 0, pl_total: 0, pl_pct: null }; }

function renderSummary(t) {
  if (!t) return;
  const plc = changeClass(t.pl_total);
  $("#pfSummary").innerHTML = `
    <div class="metric"><div class="lbl">保有銘柄数</div><div class="val">${t.count}</div></div>
    <div class="metric"><div class="lbl">投資額（取得）</div><div class="val">${yen(t.cost)}<span style="font-size:13px">円</span></div></div>
    <div class="metric"><div class="lbl">評価額（現在）</div><div class="val">${yen(t.value)}<span style="font-size:13px">円</span></div></div>
    <div class="metric"><div class="lbl">損益</div><div class="val ${plc}">${t.pl_total >= 0 ? "+" : ""}${yen(t.pl_total)}<span style="font-size:13px">円</span> <span style="font-size:14px">(${t.pl_pct == null ? "—" : (t.pl_pct >= 0 ? "+" : "") + t.pl_pct + "%"})</span></div></div>`;
}

function holdingHtml(h) {
  if (h.error) {
    return `<div class="holding"><div class="holding-head"><div class="hn"><div class="nm">${esc(h.name || h.code)}</div>
      <div class="meta">${esc(h.code)}</div></div><span class="verdict t-info">${esc(h.verdict)}</span>
      <div class="holding-actions">
        <button class="btn ghost sm" title="編集" aria-label="${esc(h.name || h.code)}を編集" onclick="editHolding(${h.id})"><i class="ti ti-pencil"></i></button>
        <button class="btn ghost sm" title="削除" aria-label="${esc(h.name || h.code)}を削除" onclick="delHolding(${h.id})"><i class="ti ti-trash"></i></button>
      </div></div>${h.memo ? `<div class="holding-body"><div class="memo"><b>メモ：</b>${esc(h.memo)}</div></div>` : ""}</div>`;
  }
  const plc = changeClass(h.pl_pct);
  const signals = (h.reasons || []).filter(r => r.severity !== "good");
  const goods = (h.reasons || []).filter(r => r.severity === "good");
  return `<div class="holding">
    <div class="holding-head">
      <div class="hn"><div class="nm">${esc(h.name)}</div>
        <div class="meta">${esc(h.code)}・${h.shares}株・取得 ${yen1(h.buy_price)}円（${esc(h.buy_date || "")}）</div></div>
      <span class="verdict t-${h.tone}"><i class="ti ti-flag"></i>${esc(h.verdict)}</span>
      <div class="pl">
        <div class="big ${plc}">${h.pl_pct == null ? "—" : (h.pl_pct >= 0 ? "+" : "") + h.pl_pct + "%"}</div>
        <div class="small ${plc}">${h.pl_total == null ? "" : (h.pl_total >= 0 ? "+" : "") + yen(h.pl_total) + "円"}　現在 ${yen1(h.price)}円</div>
      </div>
      <div class="holding-actions">
        <button class="btn ghost sm" title="編集" aria-label="${esc(h.name)}を編集" onclick="editHolding(${h.id})"><i class="ti ti-pencil"></i></button>
        <button class="btn ghost sm" title="削除" aria-label="${esc(h.name)}を削除" onclick="delHolding(${h.id})"><i class="ti ti-trash"></i></button>
      </div>
    </div>
    <div class="holding-body">
      <div class="why"><b><i class="ti ti-bulb"></i> 売り時の判定：</b>${esc(h.summary)}</div>
      ${h.memo ? `<div class="memo"><b>メモ：</b>${esc(h.memo)}</div>` : ""}
      ${signals.length ? `<div class="signal-list">${signals.map(signalHtml).join("")}</div>` : ""}
      ${goods.length ? `<div class="signal-list">${goods.map(signalHtml).join("")}</div>` : ""}
      <div class="holding-stats">
        <span>損切り目安：<b>${yen(h.stop_price)}円</b>（買値の-${h.stop_loss_pct}%）</span>
        ${h.target_price ? `<span>目標株価：<b>${yen(h.target_price)}円</b></span>` : ""}
        ${h.indicators && h.indicators.rsi != null ? `<span>RSI：<b>${h.indicators.rsi.toFixed(0)}</b></span>` : ""}
        ${h.indicators && h.indicators.sma25 != null ? `<span>25日線：<b>${yen(h.indicators.sma25)}円</b></span>` : ""}
      </div>
    </div>
  </div>`;
}

function signalHtml(s) {
  const ic = { danger: "ti-alert-octagon", warn: "ti-alert-triangle", info: "ti-eye", good: "ti-circle-check" }[s.severity] || "ti-point";
  return `<div class="signal sig-${s.severity}">
    <i class="ti ${ic} st"></i>
    <div class="st"><div class="lab">${esc(s.label)}</div><div class="det">${esc(s.detail)}</div></div>
  </div>`;
}

function delHolding(id) {
  if (!confirm("この保有銘柄を削除しますか？")) return;
  setPort(getPort().filter(h => h.id !== id));
  if (editingHoldingId === id) resetHoldingForm();
  toast("削除しました");
  loadPortfolio();
}

function readHoldingForm() {
  const codeInput = $("#pfCode").value.trim();
  const code = parseCode(codeInput);
  const m = (window._master || []).find(x => x.code === code);
  return {
    code,
    name: m ? m.name : code,
    shares: numVal($("#pfShares").value, 0),
    buy_price: numVal($("#pfBuy").value, 0),
    buy_date: $("#pfDate").value || new Date().toISOString().slice(0, 10),
    target_price: numVal($("#pfTarget").value),
    stop_loss_pct: numVal($("#pfStop").value),
    memo: $("#pfMemo").value.trim(),
  };
}

function fillHoldingForm(h) {
  $("#pfCode").value = h.code || "";
  $("#pfShares").value = h.shares ?? "";
  $("#pfBuy").value = h.buy_price ?? "";
  $("#pfDate").value = h.buy_date || new Date().toISOString().slice(0, 10);
  $("#pfTarget").value = h.target_price ?? "";
  $("#pfStop").value = h.stop_loss_pct ?? "";
  $("#pfMemo").value = h.memo || "";
}

function resetHoldingForm() {
  editingHoldingId = null;
  ["pfCode", "pfShares", "pfBuy", "pfTarget", "pfStop", "pfMemo"].forEach(id => $("#" + id).value = "");
  $("#pfDate").value = new Date().toISOString().slice(0, 10);
  $("#pfDuplicate").value = "merge";
  $("#pfDuplicate").disabled = false;
  $("#pfErr").textContent = "";
  $("#pfAdd").innerHTML = '<i class="ti ti-circle-plus"></i>登録する';
  $("#pfCancelEdit").style.display = "none";
}

function editHolding(id) {
  const port = getPort();
  const h = port.find(x => x.id === id);
  if (!h) return;
  editingHoldingId = id;
  fillHoldingForm(h);
  $("#pfDuplicate").disabled = true;
  $("#pfAdd").innerHTML = '<i class="ti ti-device-floppy"></i>更新する';
  $("#pfCancelEdit").style.display = "";
  $("#pfCode").focus();
  toast("編集内容をフォームに読み込みました");
}

function mergeHolding(existing, next) {
  const oldShares = numVal(existing.shares, 0);
  const addShares = numVal(next.shares, 0);
  const totalShares = oldShares + addShares;
  const oldCost = oldShares * numVal(existing.buy_price, 0);
  const addCost = addShares * numVal(next.buy_price, 0);
  existing.shares = totalShares;
  existing.buy_price = totalShares ? Math.round((oldCost + addCost) / totalShares * 10) / 10 : next.buy_price;
  existing.buy_date = next.buy_date || existing.buy_date;
  existing.target_price = next.target_price ?? existing.target_price ?? null;
  existing.stop_loss_pct = next.stop_loss_pct ?? existing.stop_loss_pct ?? null;
  if (next.memo) existing.memo = existing.memo ? `${existing.memo}\n${next.buy_date}: ${next.memo}` : next.memo;
}

$("#pfCancelEdit").addEventListener("click", resetHoldingForm);

$("#pfAdd").addEventListener("click", async () => {
  const item = readHoldingForm();
  $("#pfErr").textContent = "";
  if (!item.code || !item.shares || !item.buy_price) { $("#pfErr").textContent = "コード・株数・買った値段は必須です"; return; }
  if (item.shares <= 0 || item.buy_price <= 0) { $("#pfErr").textContent = "株数と買った値段は0より大きい値にしてください"; return; }
  const port = getPort();
  if (editingHoldingId != null) {
    const idx = port.findIndex(h => h.id === editingHoldingId);
    if (idx < 0) { $("#pfErr").textContent = "編集対象が見つかりません"; return; }
    port[idx] = { ...port[idx], ...item };
    setPort(port);
    toast("更新しました");
    resetHoldingForm();
    loadPortfolio();
    return;
  }
  const dup = port.find(h => h.code === item.code);
  if (dup && $("#pfDuplicate").value === "merge") {
    mergeHolding(dup, item);
    setPort(port);
    toast("平均取得単価にまとめました");
    resetHoldingForm();
    loadPortfolio();
    return;
  }
  item.id = port.reduce((m, h) => Math.max(m, h.id || 0), 0) + 1;
  port.push(item);
  setPort(port);
  toast("登録しました");
  resetHoldingForm();
  loadPortfolio();
});

// 「7203」も「トヨタ」も受け付ける。名前ならコードに変換を試みる。
function parseCode(input) {
  const m = input.match(/\d{4}/);
  if (m) return m[0];
  const hit = (window._master || []).find(x => input.includes(x.name) || x.name.includes(input));
  return hit ? hit.code : input;
}

async function quickAdd(code, name) {
  // モーダルを閉じてポートフォリオタブへ誘導し、フォームに値を入れる
  closeModal();
  $$(".tab").forEach(t => t.classList.remove("active"));
  $$(".panel").forEach(p => p.classList.remove("active"));
  $('.tab[data-tab="port"]').classList.add("active");
  $("#panel-port").classList.add("active");
  loadPortfolio();
  $("#pfCode").value = code;
  try {
    const s = await api(`/api/stock/${encodeURIComponent(code)}`);
    if (s.price) {
      $("#pfBuy").value = Math.round(s.price * 10) / 10;
      $("#pfErr").textContent = "買った値段は現在値を仮入力しています。実際の取得単価に直してください。";
    }
  } catch (e) {}
  $("#pfShares").focus();
  toast(`${name} を入力しました。買値は必ず確認してください`);
}

$("#exportJson").addEventListener("click", () => {
  const payload = {
    version: 1,
    exported_at: new Date().toISOString(),
    watchlist: getWatch(),
    portfolio: getPort(),
  };
  downloadText(`jstock-watch-backup-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(payload, null, 2));
  toast("バックアップを書き出しました");
});

$("#importJson").addEventListener("click", () => $("#importFile").click());
$("#importFile").addEventListener("change", async e => {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    const portfolio = Array.isArray(data) ? data : data.portfolio;
    const watchlist = Array.isArray(data.watchlist) ? data.watchlist : null;
    if (!Array.isArray(portfolio)) throw new Error("portfolio が見つかりません");
    if (!confirm("現在のマイ株とウォッチリストをバックアップ内容で置き換えますか？")) return;
    setPort(portfolio.map((h, i) => ({ ...h, id: h.id || i + 1 })));
    if (watchlist) setWatch(watchlist.map(String));
    resetHoldingForm();
    loadPortfolio(true);
    toast("バックアップを復元しました");
  } catch (err) {
    toast("復元できませんでした");
  }
});

$("#exportCsv").addEventListener("click", () => {
  const rows = [["code", "name", "shares", "buy_price", "buy_date", "target_price", "stop_loss_pct", "memo"]];
  getPort().forEach(h => rows.push([
    h.code, h.name, h.shares, h.buy_price, h.buy_date || "", h.target_price ?? "", h.stop_loss_pct ?? "", h.memo || "",
  ]));
  const csv = rows.map(row => row.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  downloadText(`jstock-watch-portfolio-${new Date().toISOString().slice(0, 10)}.csv`, csv, "text/csv");
  toast("CSVを書き出しました");
});

// ---------- 検索・ウォッチリスト ----------
$("#searchBtn").addEventListener("click", doSearch);
$("#searchInput").addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });

async function doSearch() {
  const q = $("#searchInput").value.trim();
  const area = $("#searchArea");
  if (!q) { area.innerHTML = ""; return; }
  setBusy(area, true);
  area.innerHTML = `<div class="loading compact"><i class="ti ti-loader-2 spin"></i><div>検索しています…</div></div>`;
  try {
    const d = await api("/api/search?q=" + encodeURIComponent(q));
    if (!d.results.length) {
      area.innerHTML = emptyState(
        "ti-search-off",
        "該当する銘柄が見つかりません",
        "4桁の証券コード、会社名の一部、業種名でも検索できます。",
        `<button class="btn" onclick="clearSearch()"><i class="ti ti-x"></i>検索をクリア</button>`
      );
      return;
    }
    area.innerHTML = `<div class="result-meta"><span>${d.results.length}件見つかりました</span></div>${d.results.map(r => resultRow(r)).join("")}`;
  } catch (e) {
    area.innerHTML = emptyState("ti-alert-triangle", "検索できませんでした", e.message);
  } finally {
    setBusy(area, false);
  }
}

function clearSearch() {
  $("#searchInput").value = "";
  $("#searchArea").innerHTML = "";
  $("#searchInput").focus();
}

function resultRow(r) {
  return `<div class="result-row">
    <div class="rn"><div class="nm">${esc(r.name)}</div><div class="meta">${esc(r.code)}・${esc(r.sector)}</div></div>
    <button class="btn sm" onclick='openDetail(${attr(r.code)})'><i class="ti ti-zoom-in"></i>分析</button>
    <button class="btn sm" onclick='addWatch(${attr(r.code)})'><i class="ti ti-eye-plus"></i>ウォッチ</button>
    <button class="btn sm primary" onclick='quickAdd(${attr(r.code)}, ${attr(r.name)})'><i class="ti ti-briefcase"></i>保有登録</button>
  </div>`;
}

function addWatch(code) {
  const c = String(code);
  const wl = getWatch();
  if (!wl.includes(c)) { wl.push(c); setWatch(wl); }
  toast("ウォッチリストに追加しました");
  loadWatchlist();
}

function loadWatchlist() {
  const area = $("#watchArea");
  const master = window._master || [];
  const items = getWatch().map(c => {
    const m = master.find(x => x.code === c);
    return { code: c, name: m ? m.name : c, sector: m ? m.sector : null };
  });
  if (!items.length) {
    area.innerHTML = emptyState(
      "ti-eye-off",
      "ウォッチリストは空です",
      "気になる銘柄を追加すると、注目候補で分析されます。",
      `<button class="btn primary" onclick="focusSearch()"><i class="ti ti-search"></i>銘柄を探す</button>`
    );
    return;
  }
  area.innerHTML = items.map(w => `<div class="result-row">
    <div class="rn"><div class="nm">${esc(w.name)}</div><div class="meta">${esc(w.code)}・${esc(w.sector || "—")}</div></div>
    <button class="btn sm" onclick='openDetail(${attr(w.code)})'><i class="ti ti-zoom-in"></i>分析</button>
    <button class="btn sm ghost" onclick='delWatch(${attr(w.code)})'><i class="ti ti-x"></i>外す</button>
  </div>`).join("");
}

function focusSearch() {
  setActiveTab("search");
  $("#searchInput").focus();
}

function delWatch(code) {
  setWatch(getWatch().filter(c => c !== String(code)));
  toast("ウォッチリストから外しました");
  loadWatchlist();
}

// ---------- ニュース ----------
let curNewsCat = "main";

async function loadNews(force) {
  const area = $("#newsArea");
  area.innerHTML = `<div class="loading"><i class="ti ti-loader-2 spin"></i><div>最新ニュースを取得しています…</div></div>`;
  try {
    const d = await api(`/api/news?cat=${encodeURIComponent(curNewsCat)}${force ? "&force=1" : ""}`);
    if (d.categories) {
      $("#newsCats").innerHTML = d.categories.map(c =>
        `<button class="news-cat ${c.key === curNewsCat ? "active" : ""}" onclick="setNewsCat(${attr(c.key)})">${esc(c.label)}</button>`).join("");
    }
    $("#newsUpdated").textContent = d.updated ? "更新 " + d.updated : "";
    if (!d.items || !d.items.length) {
      area.innerHTML = emptyState(
        "ti-news-off",
        "ニュースを取得できませんでした",
        "少し待ってから再試行してください。",
        `<button class="btn primary" onclick="loadNews(true)"><i class="ti ti-refresh"></i>再試行</button>`
      );
      return;
    }
    area.innerHTML = `<div class="news-list">${d.items.map(newsItem).join("")}</div>`;
  } catch (e) {
    area.innerHTML = emptyState(
      "ti-alert-triangle",
      "ニュースを取得できませんでした",
      e.message,
      `<button class="btn primary" onclick="loadNews(true)"><i class="ti ti-refresh"></i>再試行</button>`
    );
  }
}

function setNewsCat(cat) {
  curNewsCat = cat;
  loadNews();
}

function newsItem(n) {
  const link = esc(n.link);
  return `<div class="news-item">
    <a class="nt" href="${link}" target="_blank" rel="noopener noreferrer">${esc(n.title)} <i class="ti ti-external-link"></i></a>
    <div class="news-meta">
      <span class="src">${esc(n.source)}</span>
      ${n.relative ? `<span class="when"><i class="ti ti-clock"></i>${esc(n.relative)}</span>` : ""}
      ${n.time ? `<span>${esc(n.time)}</span>` : ""}
    </div>
    ${n.hint ? `<div class="news-hint"><i class="ti ti-bulb"></i><div><b>なぜ重要？</b> ${esc(n.hint)}</div></div>` : ""}
  </div>`;
}

// 銘柄詳細モーダル内の関連ニュース
async function loadStockNews(code) {
  const el = $("#detailNews");
  if (!el) return;
  const head = `<h4><i class="ti ti-news"></i>関連ニュース</h4>`;
  try {
    const d = await api(`/api/stock-news?code=${encodeURIComponent(code)}`);
    if (!d.items || !d.items.length) {
      el.innerHTML = head + `<div class="sub" style="color:var(--text-3)">関連ニュースは見つかりませんでした。</div>`;
      return;
    }
    el.innerHTML = head + d.items.map(n => `
      <div class="ri">
        <a href="${esc(n.link)}" target="_blank" rel="noopener noreferrer">${esc(n.title)} <i class="ti ti-external-link" style="font-size:12px"></i></a>
        <div class="m">${esc(n.source)}${n.relative ? " ・ " + esc(n.relative) : ""}</div>
      </div>`).join("");
  } catch (e) {
    el.innerHTML = head + `<div class="sub" style="color:var(--text-3)">ニュースの取得に失敗しました。</div>`;
  }
}

// ---------- 用語集 ----------
const GLOSSARY = [
  ["ti-chart-line", "移動平均線", "過去の終値を平均してなめらかにした線。5日・25日・75日・200日などがあり、線より上なら上昇基調、下なら下落基調の目安。期間が長いほど大きなトレンドを表します。"],
  ["ti-arrows-cross", "ゴールデンクロス", "短い移動平均線が長い移動平均線を下から上に抜けること。上昇に転じる「買いのサイン」とされます。"],
  ["ti-arrows-cross", "デッドクロス", "短い移動平均線が長い移動平均線を上から下に抜けること。下落に転じる「売りのサイン」とされます。"],
  ["ti-activity", "RSI", "「買われすぎ・売られすぎ」を0〜100で表す指標。一般に70以上で買われすぎ（反落注意）、30以下で売られすぎ（反発期待）と読みます。"],
  ["ti-wave-sine", "MACD", "2本の線で勢いの変化をとらえる指標。線が上向きに交差すると上昇、下向きに交差すると下落のサインとされます。"],
  ["ti-chart-arcs", "ボリンジャーバンド", "株価が動きやすい範囲を帯で示したもの。上の帯に近いほど割高、下の帯に近いほど割安の目安です。"],
  ["ti-stack-2", "出来高", "売買が成立した株数。出来高が増えると、その銘柄への注目や勢いが高まっているサインです。"],
  ["ti-scissors", "損切り（ロスカット）", "予想に反して下がったとき、損失が大きくなる前に売ること。「損は小さく」が投資で生き残る基本です。"],
  ["ti-coin", "利確（利益確定）", "値上がりした株を売って利益を確定すること。「どこで売るか」を先に決めておくのがコツです。"],
  ["ti-arrows-vertical", "52週高値・安値", "過去1年間でつけた一番高い／安い株価。今がそのレンジのどのあたりかで、株の強さを判断できます。"],
  ["ti-trending-up", "トレンド", "株価の大きな方向性。上向き（上昇トレンド）の銘柄に乗るのが順張りの基本です。"],
  ["ti-clock", "短期・中期・長期", "短期は数日〜数週間、中期は1〜6か月、長期は半年〜数年の保有を想定。期間で重視する指標が変わります。"],
  ["ti-chart-candle", "テクニカル分析", "株価チャートや移動平均線・RSIなどの「値動き」から売買のタイミングを探る方法。このアプリの『注目候補』やスコアはこれにあたります。"],
  ["ti-building-bank", "ファンダメンタル分析", "企業の業績や経済・金利・為替など「世の中の状況」から株の価値を判断する方法。このアプリの『ニュース』タブが、その材料集めに役立ちます。"],
  ["ti-news", "材料（好材料・悪材料）", "株価を動かすきっかけになる出来事のこと。決算の好調や増配は好材料、業績悪化や不祥事は悪材料。ニュースで「今、何が起きているか」を押さえましょう。"],
];
function renderGlossary() {
  if (loaded.gloss) return;
  $("#glossArea").innerHTML = GLOSSARY.map(([ic, t, d]) =>
    `<div class="gloss-item"><h4><i class="ti ${ic}"></i>${esc(t)}</h4><p>${esc(d)}</p></div>`).join("");
  loaded.gloss = true;
}

// ---------- 起動 ----------
$("#refreshBtn").addEventListener("click", async () => {
  const btn = $("#refreshBtn");
  setButtonLoading(btn, true, "更新中");
  try {
    await loadMarket();
    const active = $(".tab.active").dataset.tab;
    if (active === "news") await loadNews(true);
    else if (active === "port") await loadPortfolio(true);
    else if (active === "search") loadWatchlist();
    else if (active === "reco") await loadReco(true);
    toast("最新データに更新しました");
  } catch (e) {
    toast("更新に失敗しました");
  } finally {
    setButtonLoading(btn, false);
  }
});

async function boot() {
  // 銘柄マスター全件を取得：名前→コード変換（parseCode）と入力補完(datalist)に使う
  try {
    const r = await api("/api/master");
    window._master = r.items;
    $("#codeList").innerHTML = r.items.map(w => `<option value="${esc(w.code)}">${esc(w.name)}</option>`).join("");
    const sectors = Array.from(new Set(r.items.map(w => w.sector).filter(Boolean))).sort((a, b) => a.localeCompare(b, "ja"));
    $("#recoSector").innerHTML = '<option value="">すべて</option>' + sectors.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  } catch (e) {}
  // 初回のみ：ウォッチリストが空なら既定の主要銘柄を端末に取り込む
  if (!getWatch().length) {
    try { const d = await api("/api/defaults"); if (d.watchlist) setWatch(d.watchlist); } catch (e) {}
  }
  $("#pfDate").value = new Date().toISOString().slice(0, 10);
  loadMarket();
  const active = lsGet(LS_TAB, "reco");
  setActiveTab(["reco", "news", "port", "search", "learn"].includes(active) ? active : "reco", false);
  loadReco();
}
boot();
