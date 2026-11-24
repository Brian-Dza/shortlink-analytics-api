const SVG_NS = "http://www.w3.org/2000/svg";

function buildUtcDateSeries(clicksByDay, periodDays) {
  const countsMap = new Map();
  for (const item of clicksByDay || []) {
    countsMap.set(item.date, Number(item.clicks) || 0);
  }

  const series = [];
  const today = new Date();
  const baseUtc = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());

  for (let offset = periodDays - 1; offset >= 0; offset -= 1) {
    const dt = new Date(baseUtc - offset * 86_400_000);
    const isoDate = dt.toISOString().slice(0, 10);
    series.push({
      date: isoDate,
      shortLabel: isoDate.slice(5),
      clicks: countsMap.get(isoDate) || 0,
    });
  }
  return series;
}

function createSvgElement(tag, attrs = {}) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    el.setAttribute(key, String(value));
  }
  return el;
}

export function renderDailyClicksChart(container, clicksByDay, periodDays) {
  container.replaceChildren();
  const series = buildUtcDateSeries(clicksByDay, periodDays);
  const maxClicks = Math.max(...series.map((entry) => entry.clicks), 0);

  if (maxClicks === 0) {
    const empty = document.createElement("p");
    empty.className = "chart-empty";
    empty.textContent = "Aún no hay clics registrados en esta ventana.";
    container.appendChild(empty);
    return;
  }

  const width = 640;
  const height = 180;
  const pad = { top: 14, right: 12, bottom: 28, left: 34 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;

  const svg = createSvgElement("svg", {
    viewBox: `0 0 ${width} ${height}`,
    class: "daily-chart-svg",
    role: "img",
    "aria-label": `Gráfico de clics diarios en los últimos ${periodDays} días`,
  });

  const gridTicks = [0, Math.ceil(maxClicks / 2), maxClicks];
  const uniqueTicks = [...new Set(gridTicks)];
  for (const tickValue of uniqueTicks) {
    const y = pad.top + plotHeight - (tickValue / maxClicks) * plotHeight;
    svg.appendChild(
      createSvgElement("line", {
        x1: pad.left,
        x2: width - pad.right,
        y1: y,
        y2: y,
        class: "chart-grid-line",
      }),
    );
    const label = createSvgElement("text", {
      x: pad.left - 6,
      y: y + 3,
      "text-anchor": "end",
      class: "chart-axis-label",
    });
    label.textContent = String(tickValue);
    svg.appendChild(label);
  }

  const tooltip = document.createElement("div");
  tooltip.className = "chart-tooltip mono";
  tooltip.hidden = true;

  const slotWidth = plotWidth / series.length;
  const barWidth = Math.max(4, Math.min(28, slotWidth * 0.62));
  const labelInterval = series.length > 14 ? 5 : 1;

  series.forEach((entry, index) => {
    const barHeight = (entry.clicks / maxClicks) * plotHeight;
    const x = pad.left + index * slotWidth + (slotWidth - barWidth) / 2;
    const y = pad.top + plotHeight - barHeight;

    const bar = createSvgElement("rect", {
      x: x.toFixed(2),
      y: y.toFixed(2),
      width: barWidth.toFixed(2),
      height: Math.max(entry.clicks > 0 ? 3 : 0, barHeight).toFixed(2),
      rx: 2,
      tabindex: "0",
      class: "chart-bar",
      "aria-label": `${entry.date}: ${entry.clicks} clics`,
    });

    const showTip = () => {
      tooltip.textContent = `${entry.date} · ${entry.clicks} ${entry.clicks === 1 ? "clic" : "clics"}`;
      tooltip.style.left = `${((x + barWidth / 2) / width) * 100}%`;
      tooltip.style.top = `${Math.max(12, (y / height) * 100 - 4)}%`;
      tooltip.hidden = false;
    };
    const hideTip = () => {
      tooltip.hidden = true;
    };

    bar.addEventListener("mouseenter", showTip);
    bar.addEventListener("focus", showTip);
    bar.addEventListener("mouseleave", hideTip);
    bar.addEventListener("blur", hideTip);

    svg.appendChild(bar);

    if (index % labelInterval === 0 || index === series.length - 1) {
      const axisText = createSvgElement("text", {
        x: (x + barWidth / 2).toFixed(2),
        y: height - 8,
        "text-anchor": "middle",
        class: "chart-axis-label",
      });
      axisText.textContent = entry.shortLabel;
      svg.appendChild(axisText);
    }
  });

  container.appendChild(svg);
  container.appendChild(tooltip);
}

export function renderBreakdownBars(container, items) {
  container.replaceChildren();

  if (!Array.isArray(items) || items.length === 0) {
    const empty = document.createElement("p");
    empty.className = "chart-empty";
    empty.textContent = "Sin datos registrados";
    container.appendChild(empty);
    return;
  }

  const total = items.reduce((acc, item) => acc + item.clicks, 0);
  const max = Math.max(...items.map((item) => item.clicks), 1);

  for (const item of items) {
    const row = document.createElement("div");
    row.className = "breakdown-item";

    const meta = document.createElement("div");
    meta.className = "breakdown-meta";

    const label = document.createElement("span");
    label.className = "breakdown-label";
    label.textContent = item.label;
    label.title = item.label;

    const pct = total > 0 ? Math.round((item.clicks / total) * 100) : 0;
    const count = document.createElement("span");
    count.className = "breakdown-count mono";
    count.textContent = `${item.clicks} (${pct}%)`;

    meta.append(label, count);

    const track = document.createElement("div");
    track.className = "breakdown-track";

    const fill = document.createElement("div");
    fill.className = "breakdown-fill";
    fill.style.width = `${Math.max(4, Math.round((item.clicks / max) * 100))}%`;

    track.appendChild(fill);
    row.append(meta, track);
    container.appendChild(row);
  }
}
