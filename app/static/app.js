/* Personal Finance Manager - vanilla JS dashboard.
 *
 * No build step, no framework, no CDN: the whole SPA is this file plus the
 * FastAPI app it talks to. Charts are hand-rolled inline SVG.
 */

(() => {
  "use strict";

  const API = "/api/v1";
  const state = {
    token: localStorage.getItem("pfm_token"),
    user: JSON.parse(localStorage.getItem("pfm_user") || "null"),
    categories: [],
    accounts: [],
    page: 1,
    size: 15,
  };

  // ------------------------------------------------------------------ //
  // Helpers
  // ------------------------------------------------------------------ //
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  const escapeHtml = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (char) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
    );

  const money = (value, currency = state.user?.currency || "INR") => {
    const amount = Number(value ?? 0);
    try {
      return new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency,
        maximumFractionDigits: 2,
      }).format(amount);
    } catch {
      return `${currency} ${amount.toFixed(2)}`;
    }
  };

  const compact = (value) => {
    const amount = Number(value ?? 0);
    if (Math.abs(amount) >= 1e7) return `${(amount / 1e7).toFixed(2)}Cr`;
    if (Math.abs(amount) >= 1e5) return `${(amount / 1e5).toFixed(2)}L`;
    if (Math.abs(amount) >= 1e3) return `${(amount / 1e3).toFixed(1)}k`;
    return amount.toFixed(0);
  };

  const isoDate = (date) => date.toISOString().slice(0, 10);
  const today = () => isoDate(new Date());

  let toastTimer;
  function toast(message, kind = "info") {
    const element = $("#toast");
    element.textContent = message;
    element.style.borderLeftColor =
      kind === "error" ? "var(--negative)" : kind === "success" ? "var(--positive)" : "var(--accent)";
    element.classList.remove("is-hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => element.classList.add("is-hidden"), 4200);
  }

  async function api(path, { method = "GET", body, form, raw = false } = {}) {
    const headers = {};
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    if (body) headers["Content-Type"] = "application/json";

    const response = await fetch(`${API}${path}`, {
      method,
      headers,
      body: form ? form : body ? JSON.stringify(body) : undefined,
    });

    if (response.status === 401) {
      logout(false);
      throw new Error("Your session expired - please log in again.");
    }
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try {
        const problem = await response.json();
        detail = problem.detail || detail;
        if (problem.errors?.length) {
          detail = problem.errors.map((e) => `${e.field}: ${e.message}`).join("; ");
        }
      } catch {
        /* keep the generic message */
      }
      throw new Error(detail);
    }
    if (raw) return response;
    return response.status === 204 ? null : response.json();
  }

  // ------------------------------------------------------------------ //
  // Theme
  // ------------------------------------------------------------------ //
  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("pfm_theme", theme);
  }
  applyTheme(localStorage.getItem("pfm_theme") || "dark");
  $("#theme-toggle")?.addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });

  // ------------------------------------------------------------------ //
  // Auth
  // ------------------------------------------------------------------ //
  function showAuthError(message) {
    const element = $("#auth-error");
    element.textContent = message;
    element.classList.toggle("is-hidden", !message);
  }

  function setSession(payload) {
    state.token = payload.access_token;
    state.user = payload.user;
    localStorage.setItem("pfm_token", state.token);
    localStorage.setItem("pfm_user", JSON.stringify(state.user));
  }

  function logout(notify = true) {
    state.token = null;
    state.user = null;
    localStorage.removeItem("pfm_token");
    localStorage.removeItem("pfm_user");
    $("#app-screen").classList.add("is-hidden");
    $("#auth-screen").classList.remove("is-hidden");
    if (notify) toast("Logged out");
  }

  function enterApp() {
    $("#auth-screen").classList.add("is-hidden");
    $("#app-screen").classList.remove("is-hidden");
    $("#user-chip").textContent = `${state.user.full_name || state.user.email} · ${state.user.currency}`;
    loadReferenceData()
      .then(() => {
        loadOverview();
        loadTransactions();
        loadBudgets();
        loadGoals();
        loadRules();
      })
      .catch((error) => toast(error.message, "error"));
  }

  $$("[data-auth-tab]").forEach((tab) =>
    tab.addEventListener("click", () => {
      $$("[data-auth-tab]").forEach((other) => other.classList.toggle("is-active", other === tab));
      const isLogin = tab.dataset.authTab === "login";
      $("#login-form").classList.toggle("is-hidden", !isLogin);
      $("#register-form").classList.toggle("is-hidden", isLogin);
      showAuthError("");
    }),
  );

  $("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showAuthError("");
    try {
      const payload = await api("/auth/login", {
        method: "POST",
        body: {
          email: $("#login-email").value.trim(),
          password: $("#login-password").value,
        },
      });
      setSession(payload);
      enterApp();
    } catch (error) {
      showAuthError(error.message);
    }
  });

  $("#register-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    showAuthError("");
    try {
      const payload = await api("/auth/register", {
        method: "POST",
        body: {
          full_name: $("#register-name").value.trim() || null,
          email: $("#register-email").value.trim(),
          password: $("#register-password").value,
        },
      });
      setSession(payload);
      enterApp();
      toast("Welcome! Create an account to start adding transactions.", "success");
    } catch (error) {
      showAuthError(error.message);
    }
  });

  $("#demo-btn").addEventListener("click", async () => {
    $("#login-email").value = "demo@pfm.app";
    $("#login-password").value = "demo1234";
    $("#login-form").requestSubmit();
  });

  $("#logout-btn").addEventListener("click", () => logout());
  $("#refresh-btn").addEventListener("click", () => enterApp());

  $$("[data-tab]").forEach((button) =>
    button.addEventListener("click", () => {
      $$("[data-tab]").forEach((other) => other.classList.toggle("is-active", other === button));
      $$("[data-panel]").forEach((panel) =>
        panel.classList.toggle("is-hidden", panel.dataset.panel !== button.dataset.tab),
      );
    }),
  );

  // ------------------------------------------------------------------ //
  // Reference data
  // ------------------------------------------------------------------ //
  async function loadReferenceData() {
    const [accounts, categories] = await Promise.all([
      api("/accounts/balances"),
      api("/categories"),
    ]);
    state.accounts = accounts;
    state.categories = categories;

    const filter = $("#f-category");
    filter.innerHTML =
      '<option value="">All categories</option>' +
      categories
        .map((category) => `<option value="${category.id}">${escapeHtml(category.name)}</option>`)
        .join("");
  }

  // ------------------------------------------------------------------ //
  // Overview
  // ------------------------------------------------------------------ //
  async function loadOverview() {
    const data = await api("/dashboard");
    renderKpis(data);
    renderCashflowChart(data.trends);
    renderCategoryDonut(data.categories);
    renderInsights(data.insights);
    renderBudgetMini(data.budgets);
    renderRecent(data.recent_transactions);
    $("#export-link").href = `${API}/data/export/transactions.csv`;
  }

  function renderKpis(data) {
    const { month, net_worth: netWorth, insights } = data;
    const savingsRate = Number(month.savings_rate || 0);
    const cards = [
      {
        label: `Income · ${month.label}`,
        value: money(month.income),
        sub: "salary, freelance, other credits",
        cls: "pos",
      },
      {
        label: `Expenses · ${month.label}`,
        value: money(month.expense),
        sub: `avg ${money(month.average_daily_spend)} / day`,
        cls: "neg",
      },
      {
        label: "Net this month",
        value: money(month.net),
        sub: `savings rate ${savingsRate.toFixed(1)}%`,
        cls: Number(month.net) >= 0 ? "pos" : "neg",
      },
      {
        label: "Net worth",
        value: money(netWorth.net_worth),
        sub: `${money(netWorth.assets)} assets · ${money(netWorth.liabilities)} debt`,
        cls: Number(netWorth.net_worth) >= 0 ? "pos" : "neg",
      },
      {
        label: "Health score",
        value: `${insights.summary.health_score}/100`,
        sub: `${insights.insights.length} insight(s) · ${insights.summary.budget_alerts} alert(s)`,
        cls: insights.summary.health_score >= 60 ? "pos" : "neg",
      },
    ];

    $("#kpis").innerHTML = cards
      .map(
        (card) => `
        <article class="kpi">
          <div class="kpi-label">${escapeHtml(card.label)}</div>
          <div class="kpi-value ${card.cls}">${escapeHtml(card.value)}</div>
          <div class="kpi-sub">${escapeHtml(card.sub)}</div>
        </article>`,
      )
      .join("");
  }

  /** Grouped bar chart: income vs expense per month (pure SVG). */
  function renderCashflowChart(trends) {
    const months = trends.months || [];
    const width = 640;
    const height = 260;
    const padding = { top: 16, right: 12, bottom: 34, left: 52 };
    const innerW = width - padding.left - padding.right;
    const innerH = height - padding.top - padding.bottom;

    if (!months.length) {
      $("#chart-cashflow").innerHTML = '<p class="empty">No data yet.</p>';
      return;
    }

    const peak = Math.max(
      ...months.flatMap((month) => [Number(month.income), Number(month.expense)]),
      1,
    );
    const step = innerW / months.length;
    const barW = Math.min(26, step / 3);

    const y = (value) => padding.top + innerH - (Number(value) / peak) * innerH;
    const gridLines = [0, 0.25, 0.5, 0.75, 1]
      .map((ratio) => {
        const yPos = padding.top + innerH - ratio * innerH;
        return `
          <line x1="${padding.left}" y1="${yPos}" x2="${width - padding.right}" y2="${yPos}"
                stroke="var(--border)" stroke-dasharray="3 5" />
          <text x="${padding.left - 8}" y="${yPos + 4}" text-anchor="end"
                font-size="10" fill="var(--muted)">${compact(peak * ratio)}</text>`;
      })
      .join("");

    const bars = months
      .map((month, index) => {
        const center = padding.left + step * index + step / 2;
        const income = Number(month.income);
        const expense = Number(month.expense);
        const label = month.month.slice(5) + "/" + month.month.slice(2, 4);
        return `
          <g>
            <rect x="${center - barW - 2}" y="${y(income)}" width="${barW}"
                  height="${Math.max(padding.top + innerH - y(income), 0)}" rx="4"
                  fill="var(--positive)" opacity="0.9">
              <title>${label} income ${money(income)}</title>
            </rect>
            <rect x="${center + 2}" y="${y(expense)}" width="${barW}"
                  height="${Math.max(padding.top + innerH - y(expense), 0)}" rx="4"
                  fill="var(--negative)" opacity="0.9">
              <title>${label} expense ${money(expense)}</title>
            </rect>
            <text x="${center}" y="${height - 12}" text-anchor="middle"
                  font-size="10.5" fill="var(--muted)">${label}</text>
          </g>`;
      })
      .join("");

    $("#chart-cashflow").innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" role="img"
           aria-label="Monthly income versus expense">
        ${gridLines}
        <line x1="${padding.left}" y1="${padding.top + innerH}" x2="${width - padding.right}"
              y2="${padding.top + innerH}" stroke="var(--border)" />
        ${bars}
      </svg>
      <div class="chart-legend">
        <span><i class="legend-dot" style="background:var(--positive)"></i>Income</span>
        <span><i class="legend-dot" style="background:var(--negative)"></i>Expense</span>
        <span>Best month: <strong>${escapeHtml(trends.best_month || "–")}</strong> ·
          avg net ${money(
            Number(trends.average_monthly_income) - Number(trends.average_monthly_expense),
          )}/mo</span>
      </div>`;
  }

  /** Donut chart of category shares (pure SVG, stroke-dasharray arcs). */
  function renderCategoryDonut(breakdown) {
    const items = (breakdown.items || []).slice(0, 7);
    const total = Number(breakdown.total || 0);
    $("#category-window").textContent = `${breakdown.date_from} → ${breakdown.date_to}`;

    if (!items.length || total <= 0) {
      $("#chart-categories").innerHTML =
        '<p class="empty">No spending recorded in this period.</p>';
      return;
    }

    const size = 220;
    const radius = 82;
    const stroke = 26;
    const circumference = 2 * Math.PI * radius;
    let offset = 0;

    const arcs = items
      .map((item) => {
        const share = Number(item.total) / total;
        const dash = share * circumference;
        const arc = `
          <circle cx="${size / 2}" cy="${size / 2}" r="${radius}" fill="none"
                  stroke="${item.color}" stroke-width="${stroke}"
                  stroke-dasharray="${dash - 2} ${circumference - dash + 2}"
                  stroke-dashoffset="${-offset}"
                  transform="rotate(-90 ${size / 2} ${size / 2})">
            <title>${escapeHtml(item.name)} ${money(item.total)} (${item.share_pct}%)</title>
          </circle>`;
        offset += dash;
        return arc;
      })
      .join("");

    const legend = items
      .map(
        (item) => `
        <div style="display:flex;justify-content:space-between;gap:.75rem;width:100%">
          <span>
            <i class="legend-dot" style="background:${item.color}"></i>
            ${escapeHtml(item.icon)} ${escapeHtml(item.name)}
          </span>
          <span class="num">
            ${money(item.total)}
            <span class="muted">${item.share_pct}%</span>
            ${
              item.change_pct === null || item.change_pct === undefined
                ? ""
                : `<span class="${item.change_pct > 0 ? "neg" : "pos"}">
                     ${item.change_pct > 0 ? "▲" : "▼"}${Math.abs(item.change_pct).toFixed(0)}%
                   </span>`
            }
          </span>
        </div>`,
      )
      .join("");

    $("#chart-categories").innerHTML = `
      <div style="display:flex;gap:1.2rem;flex-wrap:wrap;align-items:center">
        <svg viewBox="0 0 ${size} ${size}" width="200" height="200" role="img"
             aria-label="Spending by category">
          ${arcs}
          <text class="donut-center" x="${size / 2}" y="${size / 2 - 4}"
                text-anchor="middle" font-size="17" fill="var(--text)">
            ${money(total)}
          </text>
          <text x="${size / 2}" y="${size / 2 + 16}" text-anchor="middle" font-size="11"
                fill="var(--muted)">total spend</text>
        </svg>
        <div style="display:grid;gap:.35rem;flex:1;min-width:200px">${legend}</div>
      </div>`;
  }

  function renderInsights(report) {
    const list = $("#insights");
    if (!report.insights.length) {
      list.innerHTML = '<li class="empty">No insights for this period yet.</li>';
      return;
    }
    list.innerHTML = report.insights
      .map(
        (insight) => `
        <li class="insight ${insight.level}">
          <h4>${escapeHtml(insight.title)}</h4>
          <p>${escapeHtml(insight.message)}</p>
          ${insight.action ? `<p class="action">→ ${escapeHtml(insight.action)}</p>` : ""}
        </li>`,
      )
      .join("");
  }

  function renderBudgetMini(budgets) {
    const container = $("#budget-mini");
    $("#budget-window").textContent = budgets.length
      ? `${budgets[0].budget.period} envelope(s)`
      : "";
    if (!budgets.length) {
      container.innerHTML =
        '<p class="empty">No budgets yet - create one in the Budgets tab.</p>';
      return;
    }
    container.innerHTML = budgets
      .slice(0, 4)
      .map((status) => budgetMarkup(status))
      .join("");
  }

  function budgetMarkup(status) {
    const pct = Math.min(status.used_pct, 100);
    const cls = status.is_over ? "over" : status.is_alert ? "warn" : "";
    return `
      <div class="budget" style="margin-bottom:.6rem">
        <div class="budget-head">
          <strong>${escapeHtml(status.category_icon)} ${escapeHtml(status.category_name)}</strong>
          <span class="${status.is_over ? "neg" : ""}">
            ${money(status.spent)} <span class="muted">/ ${money(status.budget.amount_limit)}</span>
          </span>
        </div>
        <div class="bar ${cls}"><span style="width:${pct}%"></span></div>
        <div class="budget-meta">
          <span>${status.used_pct.toFixed(0)}% used · ${status.days_remaining} day(s) left</span>
          <span>
            ${status.is_over ? "over by " + money(-status.remaining) : "safe " + money(status.safe_daily_spend) + "/day"}
            · projected ${money(status.projected_spend)}
          </span>
        </div>
      </div>`;
  }

  function renderRecent(transactions) {
    const tbody = $("#recent-table tbody");
    if (!transactions.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty">No transactions yet.</td></tr>';
      return;
    }
    tbody.innerHTML = transactions
      .map((txn) => {
        const category = state.categories.find((item) => item.id === txn.category_id);
        const account = state.accounts.find((item) => item.account.id === txn.account_id);
        return `
          <tr>
            <td>${txn.occurred_on}</td>
            <td>${escapeHtml(txn.description)}</td>
            <td>${category ? `${category.icon} ${escapeHtml(category.name)}` : '<span class="muted">–</span>'}</td>
            <td>${account ? escapeHtml(account.account.name) : "–"}</td>
            <td class="num ${txn.type === "income" ? "pos" : "neg"}">
              ${txn.type === "income" ? "+" : "−"}${money(txn.amount)}
            </td>
          </tr>`;
      })
      .join("");
  }

  // ------------------------------------------------------------------ //
  // Transactions
  // ------------------------------------------------------------------ //
  async function loadTransactions() {
    const [sort, order] = $("#f-sort").value.split(":");
    const params = new URLSearchParams({ page: state.page, size: state.size, sort, order });
    const search = $("#f-search").value.trim();
    if (search) params.set("search", search);
    if ($("#f-type").value) params.set("type", $("#f-type").value);
    if ($("#f-category").value) params.set("category_id", $("#f-category").value);
    if ($("#f-from").value) params.set("from", $("#f-from").value);
    if ($("#f-to").value) params.set("to", $("#f-to").value);

    const data = await api(`/transactions?${params.toString()}`);
    const tbody = $("#txn-table tbody");

    tbody.innerHTML = data.items.length
      ? data.items
          .map((txn) => {
            const category = state.categories.find((item) => item.id === txn.category_id);
            const account = state.accounts.find((item) => item.account.id === txn.account_id);
            return `
              <tr>
                <td>${txn.occurred_on}</td>
                <td>
                  ${escapeHtml(txn.description)}
                  ${txn.merchant ? `<div class="muted small">${escapeHtml(txn.merchant)}</div>` : ""}
                </td>
                <td>${category ? `${category.icon} ${escapeHtml(category.name)}` : '<span class="muted">–</span>'}</td>
                <td>${account ? escapeHtml(account.account.name) : "–"}</td>
                <td>${txn.tags.map((tag) => `<span class="pill">${escapeHtml(tag)}</span>`).join(" ")}</td>
                <td class="num ${txn.type === "income" ? "pos" : "neg"}">
                  ${txn.type === "income" ? "+" : "−"}${money(txn.amount)}
                </td>
                <td>
                  <button class="btn btn-ghost btn-sm" data-delete-txn="${txn.id}"
                          title="Delete">✕</button>
                </td>
              </tr>`;
          })
          .join("")
      : '<tr><td colspan="7" class="empty">No transactions match these filters.</td></tr>';

    $("#page-info").textContent = `${data.page} / ${data.pages || 1} · ${data.total} row(s)`;
    $("#page-prev").disabled = data.page <= 1;
    $("#page-next").disabled = data.page >= (data.pages || 1);

    $$("[data-delete-txn]").forEach((button) =>
      button.addEventListener("click", async () => {
        if (!confirm("Delete this transaction?")) return;
        try {
          await api(`/transactions/${button.dataset.deleteTxn}`, { method: "DELETE" });
          toast("Transaction deleted", "success");
          loadTransactions();
          loadOverview();
        } catch (error) {
          toast(error.message, "error");
        }
      }),
    );
  }

  const debounce = (fn, delay = 320) => {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), delay);
    };
  };

  $("#f-search").addEventListener("input", debounce(() => ((state.page = 1), loadTransactions())));
  ["#f-type", "#f-category", "#f-from", "#f-to", "#f-sort"].forEach((selector) =>
    $(selector).addEventListener("change", () => ((state.page = 1), loadTransactions())),
  );
  $("#f-reset").addEventListener("click", () => {
    ["#f-search", "#f-type", "#f-category", "#f-from", "#f-to"].forEach(
      (selector) => ($(selector).value = ""),
    );
    $("#f-sort").value = "occurred_on:desc";
    state.page = 1;
    loadTransactions();
  });
  $("#page-prev").addEventListener("click", () => (state.page = Math.max(1, state.page - 1), loadTransactions()));
  $("#page-next").addEventListener("click", () => (state.page += 1, loadTransactions()));

  // ------------------------------------------------------------------ //
  // Modal plumbing
  // ------------------------------------------------------------------ //
  function openModal(title, fields, onSubmit) {
    $("#modal-title").textContent = title;
    $("#modal-body").innerHTML = fields;
    $("#modal-error").classList.add("is-hidden");
    const modal = $("#modal");
    modal.showModal();

    const form = $("#modal-form");
    const handler = async (event) => {
      if (event.submitter?.value === "cancel") {
        form.removeEventListener("submit", handler);
        return;
      }
      event.preventDefault();
      try {
        await onSubmit();
        form.removeEventListener("submit", handler);
        modal.close();
      } catch (error) {
        const box = $("#modal-error");
        box.textContent = error.message;
        box.classList.remove("is-hidden");
      }
    };
    form.addEventListener("submit", handler);
  }

  function categoryOptions(kind) {
    return state.categories
      .filter((category) => !kind || category.kind === kind)
      .map((category) => `<option value="${category.id}">${category.icon} ${escapeHtml(category.name)}</option>`)
      .join("");
  }

  function accountOptions() {
    return state.accounts
      .map((item) => `<option value="${item.account.id}">${escapeHtml(item.account.name)}</option>`)
      .join("");
  }

  $("#new-txn-btn").addEventListener("click", () => {
    if (!state.accounts.length) {
      toast("Create an account first (or load sample data).", "error");
      return;
    }
    openModal(
      "Add transaction",
      `
        <label>Type
          <select id="m-type">
            <option value="expense">Expense</option>
            <option value="income">Income</option>
          </select>
        </label>
        <label>Amount
          <input id="m-amount" type="number" step="0.01" min="0.01" required placeholder="250.00" />
        </label>
        <label>Description
          <input id="m-description" required maxlength="255" placeholder="Weekly groceries" />
          <span class="muted small" id="m-suggestion"></span>
        </label>
        <label>Account <select id="m-account">${accountOptions()}</select></label>
        <label>Category <select id="m-category">${categoryOptions("expense")}</select></label>
        <label>Date <input id="m-date" type="date" value="${today()}" required /></label>
        <label>Merchant <input id="m-merchant" maxlength="120" placeholder="BigBasket" /></label>
        <label>Tags <input id="m-tags" placeholder="groceries, weekly" /></label>
      `,
      async () => {
        const type = $("#m-type").value;
        await api("/transactions", {
          method: "POST",
          body: {
            account_id: Number($("#m-account").value),
            category_id: $("#m-category").value ? Number($("#m-category").value) : null,
            amount: Number($("#m-amount").value).toFixed(2),
            type,
            description: $("#m-description").value.trim(),
            merchant: $("#m-merchant").value.trim() || null,
            occurred_on: $("#m-date").value,
            tags: $("#m-tags")
              .value.split(",")
              .map((tag) => tag.trim())
              .filter(Boolean),
          },
        });
        toast("Transaction added", "success");
        loadTransactions();
        loadOverview();
      },
    );

    // Live category suggestion from the deterministic keyword rules.
    const suggest = debounce(async () => {
      const description = $("#m-description").value.trim();
      if (description.length < 3) return;
      try {
        const result = await api(
          `/transactions/suggest-category?description=${encodeURIComponent(description)}`,
        );
        if (result.suggested_category) {
          const match = state.categories.find(
            (category) => category.name === result.suggested_category,
          );
          if (match) $("#m-category").value = String(match.id);
          $("#m-suggestion").textContent = `🤖 suggested: ${result.suggested_category} (${result.confidence})`;
        }
      } catch {
        /* suggestion is best-effort */
      }
    }, 450);
    $("#m-description").addEventListener("input", suggest);
  });

  // ------------------------------------------------------------------ //
  // Budgets
  // ------------------------------------------------------------------ //
  async function loadBudgets() {
    const budgets = await api("/budgets");
    const container = $("#budget-list");
    container.innerHTML = budgets.length
      ? budgets
          .map(
            (status) => `
        <div class="budget">
          ${budgetMarkup(status)}
          <div style="display:flex;gap:.45rem;justify-content:flex-end;margin-top:.5rem">
            <button class="btn btn-ghost btn-sm" data-delete-budget="${status.budget.id}">Delete</button>
          </div>
        </div>`,
          )
          .join("")
      : '<p class="empty">No budgets yet. Envelopes give every category a spending ceiling.</p>';

    $$("[data-delete-budget]").forEach((button) =>
      button.addEventListener("click", async () => {
        try {
          await api(`/budgets/${button.dataset.deleteBudget}`, { method: "DELETE" });
          toast("Budget deleted", "success");
          loadBudgets();
          loadOverview();
        } catch (error) {
          toast(error.message, "error");
        }
      }),
    );
  }

  $("#new-budget-btn").addEventListener("click", () => {
    const expenseCategories = state.categories.filter((category) => category.kind === "expense");
    if (!expenseCategories.length) {
      toast("No expense categories available.", "error");
      return;
    }
    openModal(
      "New budget",
      `
        <label>Category <select id="m-category">${categoryOptions("expense")}</select></label>
        <label>Limit per period
          <input id="m-limit" type="number" step="0.01" min="1" required placeholder="10000" />
        </label>
        <label>Period
          <select id="m-period">
            <option value="monthly">Monthly</option>
            <option value="weekly">Weekly</option>
            <option value="yearly">Yearly</option>
          </select>
        </label>
        <label class="checkbox"><input type="checkbox" id="m-rollover" /> Roll over unspent budget</label>
      `,
      async () => {
        await api("/budgets", {
          method: "POST",
          body: {
            category_id: Number($("#m-category").value),
            amount_limit: $("#m-limit").value,
            period: $("#m-period").value,
            rollover: $("#m-rollover").checked,
          },
        });
        toast("Budget created", "success");
        loadBudgets();
        loadOverview();
      },
    );
  });

  // ------------------------------------------------------------------ //
  // Goals
  // ------------------------------------------------------------------ //
  async function loadGoals() {
    const goals = await api("/goals");
    const container = $("#goal-list");
    container.innerHTML = goals.length
      ? goals
          .map(
            (goal) => `
        <article class="goal">
          <div style="display:flex;justify-content:space-between;gap:.5rem;align-items:center">
            <strong>${escapeHtml(goal.name)}</strong>
            <span class="pill">${goal.status}</span>
          </div>
          <div class="goal-value">${money(goal.saved_amount)}</div>
          <div class="muted small">of ${money(goal.target_amount)} ·
            ${goal.target_date ? `by ${goal.target_date}` : "no deadline"}</div>
          <div class="bar ${goal.progress_pct >= 100 ? "" : "warn"}">
            <span style="width:${Math.min(goal.progress_pct, 100)}%"></span>
          </div>
          <div class="muted small">${goal.progress_pct.toFixed(1)}% funded</div>
          <div style="display:flex;gap:.45rem">
            <button class="btn btn-ghost btn-sm" data-contribute="${goal.id}">Add money</button>
            <button class="btn btn-ghost btn-sm" data-delete-goal="${goal.id}">Delete</button>
          </div>
        </article>`,
          )
          .join("")
      : '<p class="empty">No goals yet. A 6-month emergency fund is a great first one.</p>';

    $$("[data-contribute]").forEach((button) =>
      button.addEventListener("click", () =>
        openModal(
          "Contribute to goal",
          '<label>Amount <input id="m-amount" type="number" step="0.01" min="0.01" required /></label>',
          async () => {
            await api(`/goals/${button.dataset.contribute}/contributions`, {
              method: "POST",
              body: { amount: $("#m-amount").value },
            });
            toast("Contribution recorded", "success");
            loadGoals();
            loadOverview();
          },
        ),
      ),
    );

    $$("[data-delete-goal]").forEach((button) =>
      button.addEventListener("click", async () => {
        try {
          await api(`/goals/${button.dataset.deleteGoal}`, { method: "DELETE" });
          toast("Goal deleted", "success");
          loadGoals();
        } catch (error) {
          toast(error.message, "error");
        }
      }),
    );
  }

  $("#new-goal-btn").addEventListener("click", () =>
    openModal(
      "New savings goal",
      `
        <label>Name <input id="m-name" required maxlength="120" placeholder="Emergency fund" /></label>
        <label>Target amount
          <input id="m-target" type="number" step="0.01" min="1" required placeholder="300000" />
        </label>
        <label>Already saved
          <input id="m-saved" type="number" step="0.01" min="0" value="0" />
        </label>
        <label>Target date <input id="m-date" type="date" /></label>
      `,
      async () => {
        await api("/goals", {
          method: "POST",
          body: {
            name: $("#m-name").value.trim(),
            target_amount: $("#m-target").value,
            saved_amount: $("#m-saved").value || "0",
            target_date: $("#m-date").value || null,
          },
        });
        toast("Goal created", "success");
        loadGoals();
        loadOverview();
      },
    ),
  );

  // ------------------------------------------------------------------ //
  // Recurring
  // ------------------------------------------------------------------ //
  async function loadRules() {
    const rules = await api("/recurring?include_inactive=true");
    const tbody = $("#rule-table tbody");
    tbody.innerHTML = rules.length
      ? rules
          .map(
            (rule) => `
        <tr>
          <td>${rule.next_run_on}</td>
          <td>${escapeHtml(rule.description)}</td>
          <td>every ${rule.interval} ${rule.frequency}</td>
          <td><span class="pill">${rule.type}</span></td>
          <td class="num ${rule.type === "income" ? "pos" : "neg"}">${money(rule.amount)}</td>
          <td style="display:flex;gap:.35rem">
            <button class="btn btn-ghost btn-sm" data-toggle-rule="${rule.id}"
                    data-active="${rule.is_active}">${rule.is_active ? "Pause" : "Resume"}</button>
            <button class="btn btn-ghost btn-sm" data-delete-rule="${rule.id}">✕</button>
          </td>
        </tr>`,
          )
          .join("")
      : '<tr><td colspan="6" class="empty">No recurring rules yet.</td></tr>';

    $$("[data-toggle-rule]").forEach((button) =>
      button.addEventListener("click", async () => {
        try {
          await api(`/recurring/${button.dataset.toggleRule}`, {
            method: "PATCH",
            body: { is_active: button.dataset.active !== "true" },
          });
          loadRules();
        } catch (error) {
          toast(error.message, "error");
        }
      }),
    );
    $$("[data-delete-rule]").forEach((button) =>
      button.addEventListener("click", async () => {
        try {
          await api(`/recurring/${button.dataset.deleteRule}`, { method: "DELETE" });
          toast("Rule deleted", "success");
          loadRules();
        } catch (error) {
          toast(error.message, "error");
        }
      }),
    );
  }

  $("#new-rule-btn").addEventListener("click", () => {
    if (!state.accounts.length) {
      toast("Create an account first.", "error");
      return;
    }
    openModal(
      "New recurring rule",
      `
        <label>Type
          <select id="m-type">
            <option value="expense">Expense</option>
            <option value="income">Income</option>
          </select>
        </label>
        <label>Description <input id="m-description" required placeholder="Netflix subscription" /></label>
        <label>Amount <input id="m-amount" type="number" step="0.01" min="0.01" required /></label>
        <label>Account <select id="m-account">${accountOptions()}</select></label>
        <label>Category <select id="m-category">${categoryOptions()}</select></label>
        <label>Frequency
          <select id="m-frequency">
            <option value="monthly">Monthly</option>
            <option value="weekly">Weekly</option>
            <option value="daily">Daily</option>
            <option value="yearly">Yearly</option>
          </select>
        </label>
        <label>Next run <input id="m-date" type="date" value="${today()}" required /></label>
      `,
      async () => {
        await api("/recurring", {
          method: "POST",
          body: {
            account_id: Number($("#m-account").value),
            category_id: $("#m-category").value ? Number($("#m-category").value) : null,
            description: $("#m-description").value.trim(),
            type: $("#m-type").value,
            amount: $("#m-amount").value,
            frequency: $("#m-frequency").value,
            next_run_on: $("#m-date").value,
          },
        });
        toast("Rule created", "success");
        loadRules();
      },
    );
  });

  $("#run-recurring-btn").addEventListener("click", async () => {
    try {
      const result = await api("/recurring/run", { method: "POST" });
      toast(
        result.posted ? `Posted ${result.posted} transaction(s)` : "Nothing due right now",
        result.posted ? "success" : "info",
      );
      loadRules();
      loadTransactions();
      loadOverview();
    } catch (error) {
      toast(error.message, "error");
    }
  });

  // ------------------------------------------------------------------ //
  // Import / export / sample data
  // ------------------------------------------------------------------ //
  $("#import-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = $("#import-file").files[0];
    if (!file) return;

    const form = new FormData();
    form.append("file", file);
    const dryRun = $("#import-dry").checked;

    try {
      const summary = await api(`/data/import/csv?dry_run=${dryRun}`, { method: "POST", form });
      const box = $("#import-result");
      box.textContent = JSON.stringify(summary, null, 2);
      box.classList.remove("is-hidden");
      toast(
        dryRun
          ? `Dry run: ${summary.imported} row(s) valid, ${summary.skipped} skipped`
          : `Imported ${summary.imported} row(s)`,
        "success",
      );
      if (!dryRun) {
        await loadReferenceData();
        loadTransactions();
        loadOverview();
      }
    } catch (error) {
      toast(error.message, "error");
    }
  });

  $("#seed-btn").addEventListener("click", async () => {
    if (!confirm("Generate ~6 months of sample data for this account?")) return;
    try {
      const result = await api("/data/sample", { method: "POST" });
      toast(`Added ${result.transactions} transactions and ${result.accounts} account(s)`, "success");
      await loadReferenceData();
      loadTransactions();
      loadBudgets();
      loadGoals();
      loadRules();
      loadOverview();
    } catch (error) {
      toast(error.message, "error");
    }
  });

  // ------------------------------------------------------------------ //
  // Boot
  // ------------------------------------------------------------------ //
  if (state.token && state.user) {
    api("/auth/me")
      .then((user) => {
        state.user = user;
        enterApp();
      })
      .catch(() => logout(false));
  }
})();
