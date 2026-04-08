/* global app.js — Daily Updates GitHub Pages */
/* eslint-env browser */
(function () {
  "use strict";

  // ── constants ────────────────────────────────────────────────────
  const PAGE_SIZE    = 12;
  const LATEST_COUNT = 5;   // update cards in Latest section (plus 1 note card)

  const TYPE_LABEL = {
    daily:          "Daily",
    smallchat_am:   "SmallChat AM",
    smallchat_pm:   "SmallChat PM",
  };
  const TYPE_BADGE = {
    daily:          "badge-daily",
    smallchat_am:   "badge-sm-am",
    smallchat_pm:   "badge-sm-pm",
  };

  // tag name → CSS class suffix (keeps class names ASCII-safe)
  const TAG_CLASS = {
    "Azure":        "azure",
    "AI":           "ai",
    "Microsoft":    "microsoft",
    "セキュリティ":  "security",
    "クラウド":      "cloud",
    "ニュース":      "news",
    "ビジネス":      "business",
    "SNS":          "sns",
  };

  // ── state ────────────────────────────────────────────────────────
  let allUpdates      = [];
  let filteredUpdates = [];
  let noteUrl         = "#";
  let currentPage     = 1;
  let activeTags      = new Set();
  let dateFrom        = "";
  let dateTo          = "";
  let searchQuery     = "";
  let activeTypes     = new Set(["daily", "smallchat_am", "smallchat_pm"]);

  // ── DOM helpers ──────────────────────────────────────────────────
  const $  = (sel, ctx) => (ctx || document).querySelector(sel);
  const $$ = (sel, ctx) => [...(ctx || document).querySelectorAll(sel)];

  function esc(str) {
    const d = document.createElement("div");
    d.appendChild(document.createTextNode(str ?? ""));
    return d.innerHTML;
  }

  function highlight(text, query) {
    if (!query) return esc(text);
    const safe   = esc(text);
    const re     = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
    return safe.replace(re, (m) => `<mark class="hl">${m}</mark>`);
  }

  // ── rendering ────────────────────────────────────────────────────
  function tagClass(tag) {
    return "tag-" + (TAG_CLASS[tag] || "default");
  }

  function tagsHtml(tags) {
    if (!tags || !tags.length) return "";
    return (
      '<div class="card-tags">' +
      tags
        .map(
          (t) =>
            `<span class="tag ${tagClass(t)}" data-tag="${esc(t)}">${esc(t)}</span>`
        )
        .join("") +
      "</div>"
    );
  }

  function cardHtml(u, query) {
    const badge  = TYPE_BADGE[u.type] || "badge-daily";
    const label  = TYPE_LABEL[u.type] || u.type;
    const title  = highlight(u.title, query);
    const excerpt = u.excerpt ? highlight(u.excerpt, query) : "";

    return `
<div class="card" data-date="${esc(u.date)}" data-type="${esc(u.type)}">
  <div class="card-header">
    <span class="badge ${badge}">${esc(label)}</span>
    <span class="card-date">${esc(u.date_formatted || u.date)}</span>
  </div>
  <h3 class="card-title">${title}</h3>
  ${excerpt ? `<p class="card-excerpt">${excerpt}</p>` : ""}
  ${tagsHtml(u.tags)}
  <div class="card-footer">
    <a href="${esc(u.github_url)}" target="_blank" rel="noopener" class="btn-read">Read →</a>
  </div>
</div>`;
  }

  // Small note card that sits alongside latest update cards
  function noteCardSmallHtml(url) {
    return `
<div class="card">
  <div class="card-header">
    <span class="badge badge-note">note</span>
  </div>
  <h3 class="card-title">note 記事</h3>
  <p class="card-excerpt">定期的に更新される解説・コラムを note で公開しています</p>
  <div class="card-footer">
    <a href="${esc(url)}" target="_blank" rel="noopener" class="btn-read">Open →</a>
  </div>
</div>`;
  }

  // Large note card in the SNS section
  function noteCardLargeHtml(url) {
    return `
<div class="note-card">
  <div class="note-icon">📝</div>
  <div class="note-info">
    <h3>note</h3>
    <p>最新の解説・コラムは note で公開しています</p>
    <a href="${esc(url)}" target="_blank" rel="noopener" class="btn-open">Open →</a>
  </div>
</div>`;
  }

  // ── Latest section ───────────────────────────────────────────────
  function renderLatest() {
    const latest = allUpdates.slice(0, LATEST_COUNT);
    const grid   = $("#latest-grid");
    if (latest.length === 0) {
      grid.innerHTML = '<div class="loading">アップデートがありません</div>';
      return;
    }
    grid.innerHTML =
      latest.map((u) => cardHtml(u, "")).join("") + noteCardSmallHtml(noteUrl);

    // Tag click → jump to archive with that tag active
    $$(".tag", grid).forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        const tag = el.dataset.tag;
        if (tag) {
          addTagFilter(tag);
          $("#archive").scrollIntoView({ behavior: "smooth" });
        }
      });
    });
  }

  // ── SNS / note section ───────────────────────────────────────────
  function renderNoteSection() {
    $("#note-card-container").innerHTML = noteCardLargeHtml(noteUrl);
  }

  // ── Archive section ──────────────────────────────────────────────
  function applyFilters() {
    const q = searchQuery.toLowerCase();
    filteredUpdates = allUpdates.filter((u) => {
      if (!activeTypes.has(u.type)) return false;
      if (activeTags.size > 0) {
        const uSet = new Set(u.tags || []);
        if (![...activeTags].every((t) => uSet.has(t))) return false;
      }
      if (dateFrom && u.date < dateFrom) return false;
      if (dateTo   && u.date > dateTo)   return false;
      if (q) {
        const haystack =
          (u.title || "").toLowerCase() +
          " " + (u.excerpt || "").toLowerCase() +
          " " + (u.tags || []).join(" ").toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
    currentPage = 1;
    renderPage();
  }

  function renderPage() {
    const total      = filteredUpdates.length;
    const totalPages = Math.ceil(total / PAGE_SIZE);
    const start      = (currentPage - 1) * PAGE_SIZE;
    const slice      = filteredUpdates.slice(start, start + PAGE_SIZE);

    $("#archive-count").textContent = `${total} 件`;

    const grid = $("#archive-grid");
    if (slice.length === 0) {
      grid.innerHTML = `
<div class="empty-state">
  <div class="empty-state-icon">🔍</div>
  <p>条件に一致するアップデートが見つかりませんでした</p>
</div>`;
    } else {
      grid.innerHTML = slice.map((u) => cardHtml(u, searchQuery)).join("");
      $$(".tag", grid).forEach((el) => {
        el.addEventListener("click", (e) => {
          e.stopPropagation();
          const tag = el.dataset.tag;
          if (tag) addTagFilter(tag);
        });
      });
    }

    // Pagination
    const pager = $("#pagination");
    if (totalPages <= 1) {
      pager.innerHTML = "";
      return;
    }

    const lo    = Math.max(1, currentPage - 2);
    const hi    = Math.min(totalPages, currentPage + 2);
    let html    = "";

    if (currentPage > 1)
      html += `<button class="page-btn" data-page="${currentPage - 1}">‹ 前へ</button>`;
    for (let i = lo; i <= hi; i++)
      html += `<button class="page-btn${i === currentPage ? " active" : ""}" data-page="${i}">${i}</button>`;
    if (currentPage < totalPages)
      html += `<button class="page-btn" data-page="${currentPage + 1}">次へ ›</button>`;

    pager.innerHTML = html;
    $$(".page-btn", pager).forEach((btn) => {
      btn.addEventListener("click", () => {
        currentPage = parseInt(btn.dataset.page, 10);
        renderPage();
        $("#archive").scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  // ── Tag filter buttons ───────────────────────────────────────────
  function allTagsSorted() {
    const s = new Set();
    allUpdates.forEach((u) => (u.tags || []).forEach((t) => s.add(t)));
    return [...s].sort();
  }

  function renderTagFilters() {
    const container = $("#tag-filters");
    container.innerHTML = allTagsSorted()
      .map(
        (tag) =>
          `<button class="tag-filter-btn${activeTags.has(tag) ? " active" : ""}" data-tag="${esc(tag)}">${esc(tag)}</button>`
      )
      .join("");

    $$(".tag-filter-btn", container).forEach((btn) => {
      btn.addEventListener("click", () => {
        const tag = btn.dataset.tag;
        if (activeTags.has(tag)) {
          activeTags.delete(tag);
          btn.classList.remove("active");
        } else {
          activeTags.add(tag);
          btn.classList.add("active");
        }
        syncClearTagsBtn();
        applyFilters();
      });
    });
  }

  function addTagFilter(tag) {
    activeTags.add(tag);
    renderTagFilters();
    syncClearTagsBtn();
    applyFilters();
  }

  function syncClearTagsBtn() {
    $("#clear-tags").style.display = activeTags.size ? "" : "none";
  }

  function syncClearDatesBtn() {
    $("#clear-dates").style.display = dateFrom || dateTo ? "" : "none";
  }

  // ── Event wiring ─────────────────────────────────────────────────
  function bindEvents() {
    // Global header search → filter archive
    $("#global-search").addEventListener("input", (e) => {
      searchQuery = e.target.value.trim();
      applyFilters();
    });
    $("#global-search").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        $("#archive").scrollIntoView({ behavior: "smooth" });
      }
    });

    // Date filters
    $("#date-from").addEventListener("change", (e) => {
      dateFrom = e.target.value.replace(/-/g, "");
      syncClearDatesBtn();
      applyFilters();
    });
    $("#date-to").addEventListener("change", (e) => {
      dateTo = e.target.value.replace(/-/g, "");
      syncClearDatesBtn();
      applyFilters();
    });

    // Clear buttons
    $("#clear-tags").addEventListener("click", () => {
      activeTags.clear();
      renderTagFilters();
      syncClearTagsBtn();
      applyFilters();
    });
    $("#clear-dates").addEventListener("click", () => {
      dateFrom = dateTo = "";
      $("#date-from").value = "";
      $("#date-to").value   = "";
      syncClearDatesBtn();
      applyFilters();
    });

    // Type checkboxes
    $$(".type-checkbox input").forEach((cb) => {
      cb.addEventListener("change", () => {
        activeTypes = new Set(
          $$(".type-checkbox input:checked").map((c) => c.value)
        );
        applyFilters();
      });
    });
  }

  // ── Bootstrap ────────────────────────────────────────────────────
  async function init() {
    try {
      const res  = await fetch("data.json");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      allUpdates = data.updates || [];
      noteUrl    = data.note_url || "#";

      if (data.generated_at) {
        const dt = new Date(data.generated_at);
        $("#footer-generated").textContent =
          "Data generated: " +
          dt.toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" }) +
          " JST";
      }
    } catch (err) {
      console.error("Failed to load data.json:", err);
      const msg = '<div class="loading">データの読み込みに失敗しました</div>';
      $("#latest-grid").innerHTML  = msg;
      $("#archive-grid").innerHTML = msg;
      return;
    }

    renderLatest();
    renderNoteSection();
    renderTagFilters();
    applyFilters();
    bindEvents();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
