const state = {
  data: null,
  rangeMode: "fixed",
  timer: null,
  pollMs: 30000,
};

const els = {
  canvas: document.querySelector("#flowChart"),
  sourceBadge: document.querySelector("#sourceBadge"),
  asOf: document.querySelector("#asOf"),
  nextFetch: document.querySelector("#nextFetch"),
  refreshButton: document.querySelector("#refreshButton"),
  rankingList: document.querySelector("#rankingList"),
  chartTitle: document.querySelector("#chartTitle"),
  snapshotCount: document.querySelector("#snapshotCount"),
  boardCount: document.querySelector("#boardCount"),
};

function moneyText(value) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}亿`;
}

function classForValue(value) {
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "";
}

function resizeCanvas() {
  const rect = els.canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(640, Math.floor(rect.width * dpr));
  const height = Math.max(720, Math.floor(rect.height * dpr));
  if (els.canvas.width !== width || els.canvas.height !== height) {
    els.canvas.width = width;
    els.canvas.height = height;
  }
}

function yRange(boards) {
  if (state.rangeMode === "fixed") return [-300, 60];
  const values = boards.flatMap((board) => board.history.map((point) => point.value_yi));
  values.push(...boards.map((board) => board.current_yi));
  const min = Math.min(-10, ...values);
  const max = Math.max(10, ...values);
  const pad = Math.max(8, (max - min) * 0.12);
  return [Math.floor((min - pad) / 10) * 10, Math.ceil((max + pad) / 10) * 10];
}

function drawChart(data) {
  resizeCanvas();
  const canvas = els.canvas;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const dpr = window.devicePixelRatio || 1;
  ctx.clearRect(0, 0, width, height);

  const pad = {
    left: 76 * dpr,
    right: 144 * dpr,
    top: 34 * dpr,
    bottom: 76 * dpr,
  };
  const plot = {
    x: pad.left,
    y: pad.top,
    w: width - pad.left - pad.right,
    h: height - pad.top - pad.bottom,
  };

  const [minY, maxY] = yRange(data.boards);
  const toX = (idx, count) => plot.x + (count <= 1 ? 0 : (idx / (count - 1)) * plot.w);
  const toY = (value) => plot.y + ((maxY - value) / (maxY - minY)) * plot.h;

  const grad = ctx.createLinearGradient(0, plot.y, 0, plot.y + plot.h);
  const zeroStop = Math.max(0, Math.min(1, (maxY - 0) / (maxY - minY)));
  grad.addColorStop(0, "rgba(199, 42, 58, 0.14)");
  grad.addColorStop(zeroStop, "rgba(255, 255, 255, 0.92)");
  grad.addColorStop(1, "rgba(15, 122, 78, 0.14)");
  ctx.fillStyle = grad;
  ctx.fillRect(plot.x, plot.y, plot.w, plot.h);

  ctx.font = `${14 * dpr}px Microsoft YaHei, Arial`;
  ctx.textBaseline = "middle";
  ctx.lineWidth = 1 * dpr;
  const ticks = state.rangeMode === "fixed" ? [60, 0, -60, -120, -180, -240, -300] : makeTicks(minY, maxY);
  ticks.forEach((tick) => {
    const y = toY(tick);
    ctx.strokeStyle = tick === 0 ? "#7f8782" : "#e2e6e1";
    ctx.beginPath();
    ctx.moveTo(plot.x, y);
    ctx.lineTo(plot.x + plot.w, y);
    ctx.stroke();
    ctx.fillStyle = "#4e5551";
    ctx.textAlign = "right";
    ctx.fillText(`${tick}亿`, plot.x - 12 * dpr, y);
  });

  ctx.strokeStyle = "#c9cec9";
  ctx.strokeRect(plot.x, plot.y, plot.w, plot.h);

  const maxCount = Math.max(1, ...data.boards.map((board) => board.history.length));
  data.boards.forEach((board) => {
    const points = board.history;
    if (!points.length) return;
    ctx.strokeStyle = board.color;
    ctx.lineWidth = 2.2 * dpr;
    ctx.beginPath();
    points.forEach((point, idx) => {
      const x = toX(idx, maxCount);
      const y = toY(point.value_yi);
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    const last = points[points.length - 1];
    const x = toX(points.length - 1, maxCount);
    const y = toY(last.value_yi);
    ctx.fillStyle = board.color;
    ctx.beginPath();
    ctx.arc(x, y, 4 * dpr, 0, Math.PI * 2);
    ctx.fill();
  });

  const labels = [...data.boards]
    .map((board) => ({ ...board, y: toY(board.current_yi) }))
    .sort((a, b) => a.y - b.y);
  const minGap = 24 * dpr;
  let lastY = plot.y - minGap;
  labels.forEach((label) => {
    label.labelY = Math.max(label.y, lastY + minGap);
    lastY = label.labelY;
  });
  const overflow = labels.length ? labels[labels.length - 1].labelY - (plot.y + plot.h) : 0;
  if (overflow > 0) {
    labels.forEach((label) => {
      label.labelY -= overflow;
    });
  }

  ctx.font = `${13 * dpr}px Microsoft YaHei, Arial`;
  labels.forEach((board) => {
    const text = `${board.name} ${moneyText(board.current_yi)}`;
    const labelX = plot.x + plot.w + 18 * dpr;
    const textWidth = ctx.measureText(text).width;
    const boxH = 24 * dpr;
    ctx.strokeStyle = board.color;
    ctx.lineWidth = 1 * dpr;
    ctx.beginPath();
    ctx.moveTo(plot.x + plot.w, board.y);
    ctx.lineTo(labelX, board.labelY);
    ctx.stroke();
    roundRect(ctx, labelX, board.labelY - boxH / 2, textWidth + 18 * dpr, boxH, 5 * dpr);
    ctx.fillStyle = "rgba(255,255,255,0.94)";
    ctx.fill();
    ctx.strokeStyle = board.color;
    ctx.stroke();
    ctx.fillStyle = board.color;
    ctx.textAlign = "left";
    ctx.fillText(text, labelX + 9 * dpr, board.labelY + 0.5 * dpr);
  });

  ctx.fillStyle = "#5d645f";
  ctx.textAlign = "left";
  ctx.font = `${14 * dpr}px Microsoft YaHei, Arial`;
  const firstTime = data.boards[0]?.history[0]?.time || "09:30";
  const lastTime = data.boards[0]?.history.at(-1)?.time || "--:--";
  ctx.fillText(firstTime.slice(0, 5), plot.x, plot.y + plot.h + 34 * dpr);
  ctx.textAlign = "right";
  ctx.fillText(lastTime.slice(0, 5), plot.x + plot.w, plot.y + plot.h + 34 * dpr);
}

function makeTicks(minY, maxY) {
  const span = maxY - minY;
  const step = span > 220 ? 60 : span > 100 ? 30 : 10;
  const ticks = [];
  for (let value = Math.ceil(minY / step) * step; value <= maxY; value += step) {
    ticks.push(value);
  }
  return ticks;
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
}

function renderRanking(data) {
  const ordered = [...data.boards].sort((a, b) => b.current_yi - a.current_yi);
  els.rankingList.innerHTML = ordered
    .map((board) => {
      const valueClass = classForValue(board.current_yi);
      const deltaClass = classForValue(board.delta_yi);
      return `
        <div class="rank-row">
          <span class="rank-swatch" style="background:${board.color}"></span>
          <div>
            <div class="rank-name">${board.name}</div>
            <div class="rank-code">${board.code}</div>
          </div>
          <div>
            <div class="rank-value ${valueClass}">${moneyText(board.current_yi)}</div>
            <div class="rank-delta ${deltaClass}">${moneyText(board.delta_yi)}</div>
          </div>
        </div>
      `;
    })
    .join("");
}

function setStatus(data) {
  els.sourceBadge.className = "badge";
  if (!data.ok) {
    els.sourceBadge.classList.add("error");
    els.sourceBadge.textContent = "异常";
  } else if (data.source === "mock") {
    els.sourceBadge.classList.add("mock");
    els.sourceBadge.textContent = "模拟";
  } else {
    els.sourceBadge.classList.add("ok");
    els.sourceBadge.textContent = "实时";
  }
  els.asOf.textContent = data.as_of ? data.as_of.replace("T", " ").slice(11, 19) : "--:--:--";
  els.nextFetch.textContent = `${data.next_fetch_in ?? data.poll_seconds}s`;
  const [, month, day] = data.trade_date.split("-");
  els.chartTitle.textContent = `${Number(month)}月${Number(day)}日 资金流向`;
  els.snapshotCount.textContent = `${data.snapshot_count} 个点`;
  els.boardCount.textContent = String(data.boards.length);
  if (data.error) {
    els.snapshotCount.textContent = data.error;
  }
}

async function loadData(force = false) {
  try {
    const response = await fetch(`/api/capital-flow${force ? "?force=1" : ""}`, { cache: "no-store" });
    const data = await response.json();
    state.data = data;
    state.pollMs = Math.max(5000, (data.poll_seconds || 30) * 1000);
    setStatus(data);
    renderRanking(data);
    drawChart(data);
    scheduleNext();
  } catch (error) {
    els.sourceBadge.className = "badge error";
    els.sourceBadge.textContent = "断开";
    els.snapshotCount.textContent = String(error);
    scheduleNext();
  }
}

function scheduleNext() {
  clearTimeout(state.timer);
  state.timer = setTimeout(() => loadData(false), state.pollMs);
}

document.querySelectorAll(".range-tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".range-tabs button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.rangeMode = button.dataset.range;
    if (state.data) drawChart(state.data);
  });
});

els.refreshButton.addEventListener("click", () => loadData(true));
window.addEventListener("resize", () => {
  if (state.data) drawChart(state.data);
});

loadData(true);
