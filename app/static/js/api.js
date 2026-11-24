const TOKEN_STORAGE_KEY = "shortlink_auth_token";
const EMAIL_STORAGE_KEY = "shortlink_auth_email";

export class ApiError extends Error {
  constructor({ status, code, message, details = null, retryAfter = null }) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.retryAfter = retryAfter;
  }
}

export class ApiClient {
  constructor({ onUnauthorized = null } = {}) {
    this.onUnauthorized = onUnauthorized;
    this.token = null;
    this.email = null;
    this.restoreSession();
  }

  restoreSession() {
    try {
      const savedToken = localStorage.getItem(TOKEN_STORAGE_KEY);
      const savedEmail = localStorage.getItem(EMAIL_STORAGE_KEY);
      if (savedToken && savedEmail) {
        this.token = savedToken;
        this.email = savedEmail;
      }
    } catch (_err) {
      this.token = null;
      this.email = null;
    }
  }

  setSession(token, email) {
    this.token = token;
    this.email = email;
    try {
      localStorage.setItem(TOKEN_STORAGE_KEY, token);
      localStorage.setItem(EMAIL_STORAGE_KEY, email);
    } catch (_err) {
      // Ignore storage quota or private-mode restrictions.
    }
  }

  clearSession() {
    this.token = null;
    this.email = null;
    try {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
      localStorage.removeItem(EMAIL_STORAGE_KEY);
    } catch (_err) {
      // Ignore storage errors.
    }
  }

  isAuthenticated() {
    return Boolean(this.token);
  }

  async request(path, { method = "GET", body = undefined, auth = false } = {}) {
    const headers = {};
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    const sendingToken = auth && Boolean(this.token);
    if (sendingToken) {
      headers.Authorization = `Bearer ${this.token}`;
    }

    const response = await fetch(path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });

    if (response.status === 204) {
      return null;
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch (_err) {
      payload = null;
    }

    if (!response.ok) {
      const retryHeader = response.headers.get("Retry-After");
      const retryAfter = retryHeader ? Number.parseInt(retryHeader, 10) : null;
      const errObj = payload && payload.error ? payload.error : null;

      if (response.status === 401 && sendingToken) {
        this.clearSession();
        if (typeof this.onUnauthorized === "function") {
          this.onUnauthorized();
        }
      }

      throw new ApiError({
        status: response.status,
        code: errObj?.code || `HTTP_${response.status}`,
        message: errObj?.message || "La solicitud no pudo completarse.",
        details: errObj?.details || null,
        retryAfter: Number.isFinite(retryAfter) ? retryAfter : null,
      });
    }

    return payload;
  }

  async getHealth() {
    const response = await fetch("/health", { cache: "no-store" });
    let payload = null;
    try {
      payload = await response.json();
    } catch (_err) {
      payload = null;
    }
    return {
      ok: response.ok,
      status: response.status,
      data: payload,
    };
  }

  async register(email, password) {
    return this.request("/api/v1/auth/register", {
      method: "POST",
      body: { email, password },
      auth: false,
    });
  }

  async login(email, password) {
    const data = await this.request("/api/v1/auth/login", {
      method: "POST",
      body: { email, password },
      auth: false,
    });
    this.setSession(data.access_token, email.trim().toLowerCase());
    return data;
  }

  async createLink(payload) {
    return this.request("/api/v1/links", {
      method: "POST",
      body: payload,
      auth: true,
    });
  }

  async listLinks({ page = 1, pageSize = 10, isActive = null } = {}) {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    if (isActive !== null) {
      params.set("is_active", String(isActive));
    }
    return this.request(`/api/v1/links?${params.toString()}`, {
      method: "GET",
      auth: true,
    });
  }

  async updateLink(shortCode, payload) {
    return this.request(`/api/v1/links/${encodeURIComponent(shortCode)}`, {
      method: "PATCH",
      body: payload,
      auth: true,
    });
  }

  async deleteLink(shortCode) {
    return this.request(`/api/v1/links/${encodeURIComponent(shortCode)}`, {
      method: "DELETE",
      auth: true,
    });
  }

  async getLinkStats(shortCode, days = 7) {
    return this.request(
      `/api/v1/links/${encodeURIComponent(shortCode)}/stats?days=${encodeURIComponent(String(days))}`,
      {
        method: "GET",
        auth: true,
      },
    );
  }
}
