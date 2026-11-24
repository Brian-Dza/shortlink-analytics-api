import { ApiError } from "./api.js";

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat("es-ES", {
  dateStyle: "short",
  timeStyle: "short",
});

export function showToast(message, variant = "info") {
  const region = document.getElementById("toast-region");
  if (!region) {
    return;
  }

  const toast = document.createElement("div");
  toast.className = `toast ${variant === "error" ? "toast-error" : variant === "warn" ? "toast-warn" : ""}`.trim();
  toast.textContent = message;
  region.appendChild(toast);

  window.setTimeout(() => {
    toast.remove();
  }, 3400);
}

export async function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_err) {
      // Fallback below.
    }
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();

  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch (_err) {
    copied = false;
  }
  textarea.remove();
  return copied;
}

export function formatDateTime(isoString) {
  if (!isoString) {
    return "Sin expiración";
  }
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return DATE_TIME_FORMATTER.format(date);
}

export function isExpired(isoString) {
  if (!isoString) {
    return false;
  }
  const ts = Date.parse(isoString);
  return Number.isFinite(ts) && ts <= Date.now();
}

export function toDatetimeLocalValue(isoString) {
  if (!isoString) {
    return "";
  }
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const pad = (value) => String(value).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

export function fromDatetimeLocalToUtcIso(localValue) {
  if (!localValue) {
    return null;
  }
  const parsed = new Date(localValue);
  if (Number.isNaN(parsed.getTime())) {
    throw new Error("La fecha de expiración no es válida.");
  }
  return parsed.toISOString();
}

export function formatApiError(err) {
  if (err instanceof ApiError) {
    if (Array.isArray(err.details) && err.details.length > 0) {
      const detailSummary = err.details
        .map((item) => `${item.field}: ${item.message}`)
        .join(" · ");
      return `${err.message} (${detailSummary})`;
    }
    return `${err.message} [${err.code}]`;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return "Ocurrió un error inesperado.";
}

export function setAlertMessage(element, message) {
  if (!element) {
    return;
  }
  if (!message) {
    element.textContent = "";
    element.hidden = true;
    return;
  }
  element.textContent = message;
  element.hidden = false;
}

export function bindDialogBackdropClose(dialog) {
  if (!dialog) {
    return;
  }
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      dialog.close();
    }
  });
}
