/* calendar.js — Events Calendar section for Daily Updates */
/* eslint-env browser */
(function () {
  "use strict";

  // ── DOM helpers ──────────────────────────────────────────────────
  const $  = (sel, ctx) => (ctx || document).querySelector(sel);

  function esc(str) {
    const d = document.createElement("div");
    d.appendChild(document.createTextNode(str ?? ""));
    return d.innerHTML;
  }

  // ── State ────────────────────────────────────────────────────────
  let allEvents     = [];       // raw event array from events.json
  let eventsByDate  = {};       // { "2026-05-15": [event, ...], ... }
  let currentYear   = 0;
  let currentMonth  = 0;        // 0-indexed (0=Jan)
  let selectedDate  = null;     // "YYYY-MM-DD" | null

  // ── Helpers ──────────────────────────────────────────────────────

  /** 現在時刻を Asia/Tokyo の {year, month(0-indexed), day} として返す。 */
  function nowInJst() {
    // events.json は JST 基準で生成されるため、表示側も JST に揃える。
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Tokyo",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(new Date());
    const get = (t) => parts.find((p) => p.type === t).value;
    return {
      year: Number(get("year")),
      month: Number(get("month")) - 1, // 0-indexed
      day: Number(get("day")),
    };
  }

  /** "2026/05/15 19:00" → "2026-05-15" */
  function startedAtToDate(startedAt) {
    if (!startedAt) return null;
    const m = startedAt.match(/^(\d{4})\/(\d{2})\/(\d{2})/);
    return m ? `${m[1]}-${m[2]}-${m[3]}` : null;
  }

  /** Build eventsByDate index */
  function indexEvents() {
    eventsByDate = {};
    for (const ev of allEvents) {
      const d = startedAtToDate(ev.started_at);
      if (!d) continue;
      if (!eventsByDate[d]) eventsByDate[d] = [];
      eventsByDate[d].push(ev);
    }
  }

  // ── Calendar render ──────────────────────────────────────────────

  function renderMonthLabel() {
    const label = $(`#cal-month-label`);
    if (label) {
      label.textContent =
        `${currentYear}年 ${String(currentMonth + 1).padStart(2, "0")}月`;
    }
  }

  function renderDays() {
    const container = $("#cal-days");
    if (!container) return;

    const t = nowInJst();
    const todayStr = `${t.year}-${String(t.month + 1).padStart(2, "0")}-${String(t.day).padStart(2, "0")}`;

    // First day-of-week for the month (0=Sun)
    const firstDow = new Date(currentYear, currentMonth, 1).getDay();
    // Number of days in the month
    const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();

    let html = "";

    // Total cells = leading empty + days. Pad to a full week for clean rows.
    const totalCells = firstDow + daysInMonth;
    const totalRows  = Math.ceil(totalCells / 7);

    for (let row = 0; row < totalRows; row++) {
      html += `<div class="cal-row" role="row">`;
      for (let col = 0; col < 7; col++) {
        const cellIndex = row * 7 + col;
        if (cellIndex < firstDow || cellIndex >= firstDow + daysInMonth) {
          // Leading or trailing empty cell
          html += `<div class="cal-cell cal-cell-empty" role="gridcell"></div>`;
          continue;
        }
        const day     = cellIndex - firstDow + 1;
        const dateStr = `${currentYear}-${String(currentMonth + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
        const evs     = eventsByDate[dateStr] || [];
        const hasEvs  = evs.length > 0;
        const isToday = dateStr === todayStr;
        const isSel   = dateStr === selectedDate;

        let cls = "cal-cell";
        if (hasEvs)  cls += " cal-cell-has-events";
        if (isToday) cls += " cal-cell-today";
        if (isSel)   cls += " cal-cell-selected";

        const countBadge = hasEvs
          ? `<span class="cal-event-count">${evs.length}</span>`
          : "";

        const interactiveAttrs = hasEvs
          ? ` role="button" tabindex="0"`
          : ` role="gridcell"`;

        html += `
<div class="${cls}" data-date="${dateStr}"${interactiveAttrs} aria-label="${dateStr}${hasEvs ? ` (${evs.length}件のイベント)` : ""}">
  <span class="cal-day-num">${day}</span>
  ${countBadge}
</div>`;
      }
      html += `</div>`;
    }

    container.innerHTML = html;

    // Click / keyboard handlers
    container.querySelectorAll(".cal-cell-has-events").forEach((cell) => {
      cell.addEventListener("click", () => selectDate(cell.dataset.date));
      cell.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          selectDate(cell.dataset.date);
        }
      });
    });
  }

  function selectDate(dateStr) {
    selectedDate = dateStr;

    // Re-render days to reflect new selected state
    renderDays();

    // Render event list panel
    renderDayPanel(dateStr);
  }

  function renderDayPanel(dateStr) {
    const panel = $("#cal-day-panel");
    const title = $("#cal-day-title");
    const list  = $("#cal-events-list");
    if (!panel || !title || !list) return;

    const evs = eventsByDate[dateStr] || [];
    const [y, mo, d] = dateStr.split("-");
    title.textContent = `${y}年${mo}月${d}日 のイベント (${evs.length}件)`;

    if (evs.length === 0) {
      list.innerHTML = `<li class="cal-event-item cal-event-empty">この日のイベントはありません</li>`;
    } else {
      list.innerHTML = evs
        .map((ev) => {
          const time  = ev.started_at ? ev.started_at.slice(11) : "";
          const place = ev.place || "";
          const descText = ev.description || ev.catch || "";
          const descHtml = descText ? `<p class="cal-event-catch">${esc(descText)}</p>` : "";
          const placeHtml = place
            ? `<span class="cal-event-place">📍 ${esc(place)}</span>`
            : "";
          const timeHtml = time
            ? `<span class="cal-event-time">🕐 ${esc(time)}</span>`
            : "";
          const meta = (timeHtml || placeHtml)
            ? `<div class="cal-event-meta">${timeHtml}${placeHtml}</div>`
            : "";
          const safeUrl = /^https?:\/\//.test(ev.event_url) ? ev.event_url : "#";
          return `
<li class="cal-event-item">
  <a href="${esc(safeUrl)}" target="_blank" rel="noopener noreferrer" class="cal-event-link">
    <strong class="cal-event-title">${esc(ev.title)}</strong>
    ${meta}
    ${descHtml}
  </a>
</li>`;
        })
        .join("");
    }

    panel.hidden = false;
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // ── Navigation ───────────────────────────────────────────────────

  function gotoMonth(year, month) {
    currentYear  = year;
    currentMonth = month;
    selectedDate = null;

    const panel = $("#cal-day-panel");
    if (panel) panel.hidden = true;

    renderMonthLabel();
    renderDays();
  }

  // ── Bootstrap ────────────────────────────────────────────────────

  async function initCalendar() {
    const widget = $("#calendar-widget");
    if (!widget) return;

    // Show loading
    const loadingEl = $("#cal-loading");

    try {
      const res = await fetch("events.json", { cache: "no-cache" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      allEvents = data.events || [];
    } catch (err) {
      console.error("Failed to load events.json:", err);
      if (loadingEl) {
        loadingEl.textContent = "イベントデータの読み込みに失敗しました";
      }
      return;
    }

    if (loadingEl) loadingEl.remove();

    indexEvents();

    // Set initial month to today (JST)
    const t = nowInJst();
    currentYear  = t.year;
    currentMonth = t.month;

    renderMonthLabel();
    renderDays();

    // Wire up navigation buttons
    const prevBtn = $("#cal-prev");
    const nextBtn = $("#cal-next");
    if (prevBtn) {
      prevBtn.addEventListener("click", () => {
        let m = currentMonth - 1;
        let y = currentYear;
        if (m < 0) { m = 11; y--; }
        gotoMonth(y, m);
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", () => {
        let m = currentMonth + 1;
        let y = currentYear;
        if (m > 11) { m = 0; y++; }
        gotoMonth(y, m);
      });
    }

    // Close panel button
    const closeBtn = $("#cal-close-panel");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => {
        selectedDate = null;
        const panel = $("#cal-day-panel");
        if (panel) panel.hidden = true;
        renderDays();
      });
    }
  }

  document.addEventListener("DOMContentLoaded", initCalendar);
})();
