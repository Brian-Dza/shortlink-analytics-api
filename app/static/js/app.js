import { ApiClient, ApiError } from "./api.js";
import { renderBreakdownBars, renderDailyClicksChart } from "./charts.js";
import {
  bindDialogBackdropClose,
  copyToClipboard,
  formatApiError,
  formatDateTime,
  fromDatetimeLocalToUtcIso,
  isExpired,
  setAlertMessage,
  showToast,
  toDatetimeLocalValue,
} from "./ui.js";

const THEME_STORAGE_KEY = "shortlink_theme";
const PAGE_SIZE = 10;

const state = {
  filter: "all",
  page: 1,
  totalPages: 0,
  links: [],
  authMode: "login",
  editingShortCode: null,
  deletingShortCode: null,
  statsShortCode: null,
  statsDays: 7,
  rateLimitTimerId: null,
};

const api = new ApiClient({
  onUnauthorized: () => {
    renderAuthState();
    showToast("Tu sesión expiró. Inicia sesión nuevamente.", "warn");
  },
});

const dom = {
  themeToggle: document.getElementById("theme-toggle"),
  healthBtn: document.getElementById("health-btn"),
  healthDot: document.getElementById("health-dot"),
  healthLabel: document.getElementById("health-label"),
  authGuestActions: document.getElementById("auth-guest-actions"),
  authUserActions: document.getElementById("auth-user-actions"),
  authUserEmail: document.getElementById("auth-user-email"),
  openLoginBtn: document.getElementById("open-login-btn"),
  openRegisterBtn: document.getElementById("open-register-btn"),
  guestLoginBtn: document.getElementById("guest-login-btn"),
  guestRegisterBtn: document.getElementById("guest-register-btn"),
  logoutBtn: document.getElementById("logout-btn"),
  rateLimitTier: document.getElementById("rate-limit-tier"),
  rateLimitBanner: document.getElementById("rate-limit-banner"),
  rateLimitBannerText: document.getElementById("rate-limit-banner-text"),
  shortenForm: document.getElementById("shorten-form"),
  originalUrlInput: document.getElementById("original-url-input"),
  customAliasInput: document.getElementById("custom-alias-input"),
  expiresAtInput: document.getElementById("expires-at-input"),
  shortenError: document.getElementById("shorten-error"),
  shortenSubmitBtn: document.getElementById("shorten-submit-btn"),
  shortenResult: document.getElementById("shorten-result"),
  resultShortUrl: document.getElementById("result-short-url"),
  resultCopyBtn: document.getElementById("result-copy-btn"),
  resultOpenBtn: document.getElementById("result-open-btn"),
  resultStatsBtn: document.getElementById("result-stats-btn"),
  linksTotalBadge: document.getElementById("links-total-badge"),
  linksToolbar: document.getElementById("links-toolbar"),
  linksGuestState: document.getElementById("links-guest-state"),
  linksAuthState: document.getElementById("links-auth-state"),
  linksLoading: document.getElementById("links-loading"),
  linksEmptyState: document.getElementById("links-empty-state"),
  linksTableWrap: document.getElementById("links-table-wrap"),
  linksTbody: document.getElementById("links-tbody"),
  refreshLinksBtn: document.getElementById("refresh-links-btn"),
  paginationBar: document.getElementById("pagination-bar"),
  paginationInfo: document.getElementById("pagination-info"),
  prevPageBtn: document.getElementById("prev-page-btn"),
  nextPageBtn: document.getElementById("next-page-btn"),
  authDialog: document.getElementById("auth-dialog"),
  authTabLogin: document.getElementById("auth-tab-login"),
  authTabRegister: document.getElementById("auth-tab-register"),
  authForm: document.getElementById("auth-form"),
  authEmailInput: document.getElementById("auth-email-input"),
  authPasswordInput: document.getElementById("auth-password-input"),
  authError: document.getElementById("auth-error"),
  authSubmitBtn: document.getElementById("auth-submit-btn"),
  editDialog: document.getElementById("edit-dialog"),
  editDialogCode: document.getElementById("edit-dialog-code"),
  editForm: document.getElementById("edit-form"),
  editUrlInput: document.getElementById("edit-url-input"),
  editActiveInput: document.getElementById("edit-active-input"),
  editExpiresInput: document.getElementById("edit-expires-input"),
  editClearExpiresInput: document.getElementById("edit-clear-expires-input"),
  editError: document.getElementById("edit-error"),
  editSubmitBtn: document.getElementById("edit-submit-btn"),
  deleteDialog: document.getElementById("delete-dialog"),
  deleteTargetCode: document.getElementById("delete-target-code"),
  deleteError: document.getElementById("delete-error"),
  confirmDeleteBtn: document.getElementById("confirm-delete-btn"),
  statsDialog: document.getElementById("stats-dialog"),
  statsSubtitle: document.getElementById("stats-subtitle"),
  statsError: document.getElementById("stats-error"),
  refreshStatsBtn: document.getElementById("refresh-stats-btn"),
  kpiTotalClicks: document.getElementById("kpi-total-clicks"),
  kpiWindowClicks: document.getElementById("kpi-window-clicks"),
  kpiTopBrowser: document.getElementById("kpi-top-browser"),
  kpiTopReferer: document.getElementById("kpi-top-referer"),
  statsPeriodLabel: document.getElementById("stats-period-label"),
  statsDailyChart: document.getElementById("stats-daily-chart"),
  statsBrowsers: document.getElementById("stats-browsers"),
  statsOs: document.getElementById("stats-os"),
  statsDevices: document.getElementById("stats-devices"),
  statsReferers: document.getElementById("stats-referers"),
};

function updateThemeToggleLabel() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  dom.themeToggle.textContent = current === "dark" ? "Tema: Oscuro" : "Tema: Claro";
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch (_err) {
    // Ignore storage failures.
  }
  updateThemeToggleLabel();
}

async function refreshHealth() {
  dom.healthDot.className = "status-dot status-dot-muted";
  dom.healthLabel.textContent = "Verificando...";

  try {
    const health = await api.getHealth();
    const pg = health.data?.services?.postgres || "down";
    const redis = health.data?.services?.redis || "down";

    if (health.ok && pg === "up" && redis === "up") {
      dom.healthDot.className = "status-dot status-dot-ok";
      dom.healthLabel.textContent = "PG up · Redis up";
    } else {
      dom.healthDot.className = "status-dot status-dot-warn";
      dom.healthLabel.textContent = `Degradado · PG ${pg} / Redis ${redis}`;
    }
  } catch (_err) {
    dom.healthDot.className = "status-dot status-dot-error";
    dom.healthLabel.textContent = "API sin respuesta";
  }
}

function startRateLimitCountdown(seconds) {
  if (state.rateLimitTimerId !== null) {
    window.clearInterval(state.rateLimitTimerId);
    state.rateLimitTimerId = null;
  }

  let remaining = Math.max(1, Number(seconds) || 60);
  const updateBanner = () => {
    dom.rateLimitBannerText.textContent = `Límite de peticiones alcanzado (HTTP 429). Podrás crear otro enlace en ${remaining}s.`;
    dom.rateLimitBanner.hidden = false;
  };

  updateBanner();
  state.rateLimitTimerId = window.setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      window.clearInterval(state.rateLimitTimerId);
      state.rateLimitTimerId = null;
      dom.rateLimitBanner.hidden = true;
      return;
    }
    updateBanner();
  }, 1000);
}

function renderAuthState() {
  const authed = api.isAuthenticated();
  dom.authGuestActions.hidden = authed;
  dom.authUserActions.hidden = !authed;
  dom.authUserEmail.textContent = authed ? api.email : "";
  dom.rateLimitTier.textContent = authed
    ? "Autenticado · 30 req/min"
    : "Anónimo · 10 req/min";

  dom.linksGuestState.hidden = authed;
  dom.linksAuthState.hidden = !authed;
  dom.linksToolbar.hidden = !authed;

  if (!authed) {
    state.links = [];
    state.totalPages = 0;
    dom.linksTotalBadge.textContent = "0";
    dom.shortenResult.hidden = true;
    dom.resultStatsBtn.hidden = true;
  } else {
    void loadLinks();
  }
}

function openAuthDialog(mode = "login") {
  setAuthMode(mode);
  setAlertMessage(dom.authError, "");
  dom.authForm.reset();
  dom.authDialog.showModal();
  dom.authEmailInput.focus();
}

function setAuthMode(mode) {
  state.authMode = mode;
  const isLogin = mode === "login";
  dom.authTabLogin.classList.toggle("is-active", isLogin);
  dom.authTabRegister.classList.toggle("is-active", !isLogin);
  dom.authTabLogin.setAttribute("aria-selected", String(isLogin));
  dom.authTabRegister.setAttribute("aria-selected", String(!isLogin));
  dom.authPasswordInput.autocomplete = isLogin ? "current-password" : "new-password";
  dom.authSubmitBtn.textContent = isLogin ? "Iniciar sesión" : "Crear cuenta";
  setAlertMessage(dom.authError, "");
}

async function handleAuthSubmit(event) {
  event.preventDefault();
  setAlertMessage(dom.authError, "");

  const email = dom.authEmailInput.value.trim();
  const password = dom.authPasswordInput.value;
  if (!email || !password) {
    setAlertMessage(dom.authError, "Completa tu correo y contraseña.");
    return;
  }

  dom.authSubmitBtn.disabled = true;
  try {
    if (state.authMode === "register") {
      await api.register(email, password);
      await api.login(email, password);
      showToast("Cuenta creada y sesión iniciada.");
    } else {
      await api.login(email, password);
      showToast("Sesión iniciada correctamente.");
    }
    dom.authDialog.close();
    renderAuthState();
  } catch (err) {
    setAlertMessage(dom.authError, formatApiError(err));
  } finally {
    dom.authSubmitBtn.disabled = false;
  }
}

async function handleShortenSubmit(event) {
  event.preventDefault();
  setAlertMessage(dom.shortenError, "");

  const originalUrl = dom.originalUrlInput.value.trim();
  const customAlias = dom.customAliasInput.value.trim();
  const expiresLocal = dom.expiresAtInput.value;

  if (!originalUrl) {
    setAlertMessage(dom.shortenError, "Ingresa una URL de destino válida.");
    return;
  }

  const payload = { original_url: originalUrl };
  if (customAlias) {
    payload.custom_alias = customAlias;
  }
  if (expiresLocal) {
    try {
      payload.expires_at = fromDatetimeLocalToUtcIso(expiresLocal);
    } catch (err) {
      setAlertMessage(dom.shortenError, formatApiError(err));
      return;
    }
  }

  dom.shortenSubmitBtn.disabled = true;
  try {
    const created = await api.createLink(payload);
    dom.resultShortUrl.textContent = created.short_url;
    dom.resultShortUrl.href = `/${encodeURIComponent(created.short_code)}`;
    dom.resultOpenBtn.href = `/${encodeURIComponent(created.short_code)}`;
    dom.resultCopyBtn.dataset.url = created.short_url;
    dom.resultStatsBtn.dataset.code = created.short_code;
    dom.resultStatsBtn.hidden = !api.isAuthenticated();
    dom.shortenResult.hidden = false;

    dom.shortenForm.reset();
    showToast(`Enlace /${created.short_code} creado.`);

    if (api.isAuthenticated()) {
      state.page = 1;
      await loadLinks();
    }
  } catch (err) {
    if (err instanceof ApiError && err.status === 429 && err.retryAfter) {
      startRateLimitCountdown(err.retryAfter);
    }
    setAlertMessage(dom.shortenError, formatApiError(err));
  } finally {
    dom.shortenSubmitBtn.disabled = false;
  }
}

function buildLinkRow(link) {
  const tr = document.createElement("tr");

  const codeTd = document.createElement("td");
  const codeLink = document.createElement("a");
  codeLink.className = "code-link mono";
  codeLink.href = `/${encodeURIComponent(link.short_code)}`;
  codeLink.target = "_blank";
  codeLink.rel = "noopener noreferrer";
  codeLink.textContent = `/${link.short_code}`;
  codeTd.appendChild(codeLink);

  const destTd = document.createElement("td");
  destTd.className = "dest-cell";
  const destSpan = document.createElement("span");
  destSpan.className = "dest-url";
  destSpan.textContent = link.original_url;
  destSpan.title = link.original_url;
  destTd.appendChild(destSpan);

  const statusTd = document.createElement("td");
  const statusBadge = document.createElement("span");
  if (!link.is_active) {
    statusBadge.className = "badge badge-muted";
    statusBadge.textContent = "Inactivo";
  } else if (isExpired(link.expires_at)) {
    statusBadge.className = "badge badge-warn";
    statusBadge.textContent = "Expirado";
  } else {
    statusBadge.className = "badge badge-ok";
    statusBadge.textContent = "Activo";
  }
  statusTd.appendChild(statusBadge);

  const expTd = document.createElement("td");
  expTd.className = "mono";
  expTd.textContent = formatDateTime(link.expires_at);

  const actionsTd = document.createElement("td");
  actionsTd.className = "col-actions";
  const actionsWrap = document.createElement("div");
  actionsWrap.className = "row-actions";

  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "btn btn-ghost btn-sm";
  copyBtn.textContent = "Copiar";
  copyBtn.addEventListener("click", async () => {
    const fullUrl = `${window.location.origin}/${link.short_code}`;
    const ok = await copyToClipboard(fullUrl);
    showToast(ok ? "URL copiada al portapapeles." : "No se pudo copiar.", ok ? "info" : "warn");
  });

  const statsBtn = document.createElement("button");
  statsBtn.type = "button";
  statsBtn.className = "btn btn-secondary btn-sm";
  statsBtn.textContent = "Analíticas";
  statsBtn.addEventListener("click", () => {
    void openStatsDialog(link.short_code);
  });

  const editBtn = document.createElement("button");
  editBtn.type = "button";
  editBtn.className = "btn btn-ghost btn-sm";
  editBtn.textContent = "Editar";
  editBtn.addEventListener("click", () => {
    openEditDialog(link);
  });

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "btn btn-ghost btn-sm";
  deleteBtn.textContent = "Eliminar";
  deleteBtn.addEventListener("click", () => {
    openDeleteDialog(link.short_code);
  });

  actionsWrap.append(copyBtn, statsBtn, editBtn, deleteBtn);
  actionsTd.appendChild(actionsWrap);

  tr.append(codeTd, destTd, statusTd, expTd, actionsTd);
  return tr;
}

async function loadLinks() {
  if (!api.isAuthenticated()) {
    return;
  }

  dom.linksLoading.hidden = false;
  dom.linksEmptyState.hidden = true;
  dom.linksTableWrap.hidden = true;
  dom.paginationBar.hidden = true;

  const isActive =
    state.filter === "active" ? true : state.filter === "inactive" ? false : null;

  try {
    const data = await api.listLinks({
      page: state.page,
      pageSize: PAGE_SIZE,
      isActive,
    });
    state.links = data.items || [];
    state.totalPages = data.total_pages || 0;
    dom.linksTotalBadge.textContent = String(data.total ?? 0);

    dom.linksTbody.replaceChildren();
    if (state.links.length === 0) {
      dom.linksEmptyState.hidden = false;
    } else {
      for (const link of state.links) {
        dom.linksTbody.appendChild(buildLinkRow(link));
      }
      dom.linksTableWrap.hidden = false;
      dom.paginationInfo.textContent = `Página ${data.page} de ${Math.max(1, data.total_pages)} · ${data.total} en total`;
      dom.prevPageBtn.disabled = data.page <= 1;
      dom.nextPageBtn.disabled = data.page >= data.total_pages;
      dom.paginationBar.hidden = false;
    }
  } catch (err) {
    if (api.isAuthenticated()) {
      showToast(formatApiError(err), "error");
    }
  } finally {
    dom.linksLoading.hidden = true;
  }
}

function openEditDialog(link) {
  state.editingShortCode = link.short_code;
  dom.editDialogCode.textContent = `/${link.short_code}`;
  dom.editUrlInput.value = link.original_url;
  dom.editActiveInput.checked = Boolean(link.is_active);
  dom.editExpiresInput.value = toDatetimeLocalValue(link.expires_at);
  dom.editClearExpiresInput.checked = !link.expires_at;
  dom.editExpiresInput.disabled = dom.editClearExpiresInput.checked;
  setAlertMessage(dom.editError, "");
  dom.editDialog.showModal();
  dom.editUrlInput.focus();
}

async function handleEditSubmit(event) {
  event.preventDefault();
  if (!state.editingShortCode) {
    return;
  }
  setAlertMessage(dom.editError, "");

  const originalUrl = dom.editUrlInput.value.trim();
  if (!originalUrl) {
    setAlertMessage(dom.editError, "La URL de destino no puede estar vacía.");
    return;
  }

  const payload = {
    original_url: originalUrl,
    is_active: dom.editActiveInput.checked,
  };

  if (dom.editClearExpiresInput.checked) {
    payload.expires_at = null;
  } else if (dom.editExpiresInput.value) {
    try {
      payload.expires_at = fromDatetimeLocalToUtcIso(dom.editExpiresInput.value);
    } catch (err) {
      setAlertMessage(dom.editError, formatApiError(err));
      return;
    }
  }

  dom.editSubmitBtn.disabled = true;
  try {
    await api.updateLink(state.editingShortCode, payload);
    dom.editDialog.close();
    showToast(`Enlace /${state.editingShortCode} actualizado e invalidado en Redis.`);
    await loadLinks();
  } catch (err) {
    setAlertMessage(dom.editError, formatApiError(err));
  } finally {
    dom.editSubmitBtn.disabled = false;
  }
}

function openDeleteDialog(shortCode) {
  state.deletingShortCode = shortCode;
  dom.deleteTargetCode.textContent = `/${shortCode}`;
  setAlertMessage(dom.deleteError, "");
  dom.deleteDialog.showModal();
}

async function handleConfirmDelete() {
  if (!state.deletingShortCode) {
    return;
  }
  setAlertMessage(dom.deleteError, "");
  dom.confirmDeleteBtn.disabled = true;

  try {
    const code = state.deletingShortCode;
    await api.deleteLink(code);
    dom.deleteDialog.close();
    if (dom.resultStatsBtn.dataset.code === code) {
      dom.shortenResult.hidden = true;
    }
    showToast(`Enlace /${code} eliminado.`);
    if (state.links.length === 1 && state.page > 1) {
      state.page -= 1;
    }
    await loadLinks();
  } catch (err) {
    setAlertMessage(dom.deleteError, formatApiError(err));
  } finally {
    dom.confirmDeleteBtn.disabled = false;
  }
}

async function openStatsDialog(shortCode) {
  state.statsShortCode = shortCode;
  dom.statsSubtitle.textContent = `/${shortCode}`;
  if (!dom.statsDialog.open) {
    dom.statsDialog.showModal();
  }
  await loadStats();
}

async function loadStats() {
  if (!state.statsShortCode) {
    return;
  }
  setAlertMessage(dom.statsError, "");
  dom.statsPeriodLabel.textContent = `Últimos ${state.statsDays} días`;
  dom.refreshStatsBtn.disabled = true;

  try {
    const stats = await api.getLinkStats(state.statsShortCode, state.statsDays);
    dom.statsSubtitle.textContent = `/${stats.short_code} -> ${stats.original_url}`;
    const windowClicks = (stats.clicks_by_day || []).reduce(
      (sum, item) => sum + item.clicks,
      0,
    );

    dom.kpiTotalClicks.textContent = String(stats.total_clicks);
    dom.kpiWindowClicks.textContent = String(windowClicks);
    dom.kpiTopBrowser.textContent = stats.top_browsers?.[0]?.label || "—";
    dom.kpiTopReferer.textContent = stats.top_referers?.[0]?.label || "—";

    renderDailyClicksChart(dom.statsDailyChart, stats.clicks_by_day, state.statsDays);
    renderBreakdownBars(dom.statsBrowsers, stats.top_browsers);
    renderBreakdownBars(dom.statsOs, stats.top_os);
    renderBreakdownBars(dom.statsDevices, stats.top_devices);
    renderBreakdownBars(dom.statsReferers, stats.top_referers);
  } catch (err) {
    setAlertMessage(dom.statsError, formatApiError(err));
  } finally {
    dom.refreshStatsBtn.disabled = false;
  }
}

function bindEvents() {
  updateThemeToggleLabel();
  dom.themeToggle.addEventListener("click", toggleTheme);
  dom.healthBtn.addEventListener("click", () => {
    void refreshHealth();
  });

  dom.openLoginBtn.addEventListener("click", () => openAuthDialog("login"));
  dom.openRegisterBtn.addEventListener("click", () => openAuthDialog("register"));
  dom.guestLoginBtn.addEventListener("click", () => openAuthDialog("login"));
  dom.guestRegisterBtn.addEventListener("click", () => openAuthDialog("register"));
  dom.logoutBtn.addEventListener("click", () => {
    api.clearSession();
    renderAuthState();
    showToast("Sesión cerrada.");
  });

  dom.authTabLogin.addEventListener("click", () => setAuthMode("login"));
  dom.authTabRegister.addEventListener("click", () => setAuthMode("register"));
  dom.authForm.addEventListener("submit", (event) => {
    void handleAuthSubmit(event);
  });

  dom.shortenForm.addEventListener("submit", (event) => {
    void handleShortenSubmit(event);
  });

  dom.resultCopyBtn.addEventListener("click", async () => {
    const url = dom.resultCopyBtn.dataset.url || dom.resultShortUrl.textContent;
    if (!url) {
      return;
    }
    const ok = await copyToClipboard(url);
    showToast(ok ? "URL copiada al portapapeles." : "No se pudo copiar.", ok ? "info" : "warn");
  });

  dom.resultStatsBtn.addEventListener("click", () => {
    const code = dom.resultStatsBtn.dataset.code;
    if (code) {
      void openStatsDialog(code);
    }
  });

  for (const filterBtn of document.querySelectorAll("[data-filter]")) {
    filterBtn.addEventListener("click", () => {
      state.filter = filterBtn.dataset.filter || "all";
      state.page = 1;
      for (const btn of document.querySelectorAll("[data-filter]")) {
        btn.classList.toggle("is-active", btn === filterBtn);
      }
      void loadLinks();
    });
  }

  dom.refreshLinksBtn.addEventListener("click", () => {
    void loadLinks();
  });
  dom.prevPageBtn.addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      void loadLinks();
    }
  });
  dom.nextPageBtn.addEventListener("click", () => {
    if (state.page < state.totalPages) {
      state.page += 1;
      void loadLinks();
    }
  });

  dom.editClearExpiresInput.addEventListener("change", () => {
    const cleared = dom.editClearExpiresInput.checked;
    dom.editExpiresInput.disabled = cleared;
    if (cleared) {
      dom.editExpiresInput.value = "";
    }
  });
  dom.editForm.addEventListener("submit", (event) => {
    void handleEditSubmit(event);
  });

  dom.confirmDeleteBtn.addEventListener("click", () => {
    void handleConfirmDelete();
  });

  for (const daysBtn of document.querySelectorAll("[data-stats-days]")) {
    daysBtn.addEventListener("click", () => {
      const nextDays = Number.parseInt(daysBtn.dataset.statsDays || "7", 10);
      state.statsDays = nextDays === 30 ? 30 : 7;
      for (const btn of document.querySelectorAll("[data-stats-days]")) {
        btn.classList.toggle("is-active", btn === daysBtn);
      }
      void loadStats();
    });
  }
  dom.refreshStatsBtn.addEventListener("click", () => {
    void loadStats();
  });

  for (const closeBtn of document.querySelectorAll("[data-close-dialog]")) {
    closeBtn.addEventListener("click", () => {
      const targetId = closeBtn.dataset.closeDialog;
      const dialog = targetId ? document.getElementById(targetId) : null;
      if (dialog instanceof HTMLDialogElement) {
        dialog.close();
      }
    });
  }

  bindDialogBackdropClose(dom.authDialog);
  bindDialogBackdropClose(dom.editDialog);
  bindDialogBackdropClose(dom.deleteDialog);
  bindDialogBackdropClose(dom.statsDialog);
}

bindEvents();
renderAuthState();
void refreshHealth();
