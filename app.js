/* Pixel Doodle — a Magna-Doodle-style pixel art tool */
(() => {
  "use strict";

  const canvas = document.getElementById("board");
  const ctx = canvas.getContext("2d");
  const CSS_SIZE = canvas.width; // internal pixel resolution (square)

  // ---- State ----
  const state = {
    grid: 16,
    tool: "pen",
    color: "#111111",
    showGrid: true,
    pixels: [],        // flat array of color strings or null
    drawing: false,
    lastCell: -1,
  };

  const undoStack = [];
  const redoStack = [];

  const PALETTE = [
    "#111111", "#ffffff", "#e23b3b", "#ff8c42", "#ffd23f", "#6ecb63",
    "#3aa7ff", "#4dd2ff", "#8a5cff", "#ff5ea8", "#7a4a2b", "#9aa0a6",
  ];

  // ---- Helpers ----
  const cellSize = () => CSS_SIZE / state.grid;

  function newBoard(fill = null) {
    state.pixels = new Array(state.grid * state.grid).fill(fill);
  }

  function snapshot() {
    return state.pixels.slice();
  }

  function pushUndo() {
    undoStack.push(snapshot());
    if (undoStack.length > 100) undoStack.shift();
    redoStack.length = 0;
  }

  // ---- Rendering ----
  function render() {
    const cs = cellSize();
    ctx.clearRect(0, 0, CSS_SIZE, CSS_SIZE);

    // base screen color
    ctx.fillStyle = "#bfc4b3";
    ctx.fillRect(0, 0, CSS_SIZE, CSS_SIZE);

    for (let i = 0; i < state.pixels.length; i++) {
      const c = state.pixels[i];
      if (!c) continue;
      const x = (i % state.grid) * cs;
      const y = Math.floor(i / state.grid) * cs;
      ctx.fillStyle = c;
      ctx.fillRect(x, y, cs, cs);
    }

    if (state.showGrid) {
      ctx.strokeStyle = "rgba(0,0,0,0.08)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let i = 0; i <= state.grid; i++) {
        const p = Math.round(i * cs) + 0.5;
        ctx.moveTo(p, 0); ctx.lineTo(p, CSS_SIZE);
        ctx.moveTo(0, p); ctx.lineTo(CSS_SIZE, p);
      }
      ctx.stroke();
    }
  }

  // ---- Coordinate mapping ----
  function cellFromEvent(e) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = CSS_SIZE / rect.width;
    const scaleY = CSS_SIZE / rect.height;
    const x = (e.clientX - rect.left) * scaleX;
    const y = (e.clientY - rect.top) * scaleY;
    const cx = Math.floor(x / cellSize());
    const cy = Math.floor(y / cellSize());
    if (cx < 0 || cy < 0 || cx >= state.grid || cy >= state.grid) return -1;
    return cy * state.grid + cx;
  }

  // ---- Tools ----
  function applyTool(idx) {
    if (idx < 0) return;

    if (state.tool === "picker") {
      const c = state.pixels[idx];
      if (c) setColor(c);
      return;
    }
    if (state.tool === "fill") {
      floodFill(idx);
      render();
      return;
    }
    if (idx === state.lastCell) return;
    state.lastCell = idx;

    if (state.tool === "eraser") {
      state.pixels[idx] = null;
    } else {
      state.pixels[idx] = state.color;
    }
    render();
  }

  function floodFill(idx) {
    const target = state.pixels[idx];
    const replacement = state.color;
    if (target === replacement) return;
    const stack = [idx];
    const g = state.grid;
    while (stack.length) {
      const i = stack.pop();
      if (state.pixels[i] !== target) continue;
      state.pixels[i] = replacement;
      const x = i % g, y = Math.floor(i / g);
      if (x > 0) stack.push(i - 1);
      if (x < g - 1) stack.push(i + 1);
      if (y > 0) stack.push(i - g);
      if (y < g - 1) stack.push(i + g);
    }
  }

  // ---- Pointer events ----
  canvas.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    try { canvas.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
    pushUndo();
    state.drawing = true;
    state.lastCell = -1;
    applyTool(cellFromEvent(e));
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!state.drawing) return;
    applyTool(cellFromEvent(e));
  });
  const endStroke = () => { state.drawing = false; state.lastCell = -1; };
  canvas.addEventListener("pointerup", endStroke);
  canvas.addEventListener("pointercancel", endStroke);
  window.addEventListener("blur", endStroke);

  // ---- UI wiring ----
  function setTool(tool) {
    state.tool = tool;
    document.querySelectorAll(".tool-btn").forEach((b) =>
      b.classList.toggle("active", b.dataset.tool === tool));
  }
  document.querySelectorAll(".tool-btn").forEach((b) =>
    b.addEventListener("click", () => setTool(b.dataset.tool)));

  function setColor(color) {
    state.color = color;
    document.getElementById("colorInput").value = color;
    document.querySelectorAll(".swatch").forEach((s) =>
      s.classList.toggle("active", s.dataset.color === color));
  }

  // build palette
  const paletteEl = document.getElementById("palette");
  PALETTE.forEach((color) => {
    const s = document.createElement("button");
    s.className = "swatch";
    s.dataset.color = color;
    s.style.background = color;
    s.title = color;
    s.addEventListener("click", () => { setColor(color); if (state.tool === "eraser") setTool("pen"); });
    paletteEl.appendChild(s);
  });

  document.getElementById("colorInput").addEventListener("input", (e) => {
    setColor(e.target.value);
    if (state.tool === "eraser") setTool("pen");
  });

  document.getElementById("gridSize").addEventListener("change", (e) => {
    const newGrid = parseInt(e.target.value, 10);
    // resample: keep drawing roughly by scaling nearest-neighbour
    const old = state.pixels;
    const oldGrid = state.grid;
    const next = new Array(newGrid * newGrid).fill(null);
    for (let y = 0; y < newGrid; y++) {
      for (let x = 0; x < newGrid; x++) {
        const sx = Math.floor(x * oldGrid / newGrid);
        const sy = Math.floor(y * oldGrid / newGrid);
        next[y * newGrid + x] = old[sy * oldGrid + sx] || null;
      }
    }
    pushUndo();
    state.grid = newGrid;
    state.pixels = next;
    render();
  });

  document.getElementById("gridLines").addEventListener("change", (e) => {
    state.showGrid = e.target.checked;
    render();
  });

  // Actions
  document.getElementById("clearBtn").addEventListener("click", () => {
    pushUndo();
    newBoard(null);
    render();
  });

  document.getElementById("undoBtn").addEventListener("click", undo);
  document.getElementById("redoBtn").addEventListener("click", redo);

  function undo() {
    if (!undoStack.length) return;
    redoStack.push(snapshot());
    state.pixels = undoStack.pop();
    render();
  }
  function redo() {
    if (!redoStack.length) return;
    undoStack.push(snapshot());
    state.pixels = redoStack.pop();
    render();
  }

  // Shake to erase
  const shakeBtn = document.getElementById("shakeBtn");
  const doodleEl = document.querySelector(".doodle");
  shakeBtn.addEventListener("click", () => {
    pushUndo();
    doodleEl.classList.remove("shaking");
    void doodleEl.offsetWidth; // reflow to restart animation
    doodleEl.classList.add("shaking");
    // erase mid-shake for the classic effect
    setTimeout(() => { newBoard(null); render(); }, 180);
    setTimeout(() => doodleEl.classList.remove("shaking"), 550);
  });

  // Export PNG
  document.getElementById("exportBtn").addEventListener("click", () => {
    const scale = parseInt(document.getElementById("exportScale").value, 10);
    const size = state.grid * scale;
    const out = document.createElement("canvas");
    out.width = size; out.height = size;
    const octx = out.getContext("2d");
    for (let i = 0; i < state.pixels.length; i++) {
      const c = state.pixels[i];
      if (!c) continue;
      const x = (i % state.grid) * scale;
      const y = Math.floor(i / state.grid) * scale;
      octx.fillStyle = c;
      octx.fillRect(x, y, scale, scale);
    }
    const link = document.createElement("a");
    link.download = `pixel-doodle-${state.grid}x${state.grid}.png`;
    link.href = out.toDataURL("image/png");
    link.click();
  });

  // Keyboard shortcuts
  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "z") {
      e.preventDefault();
      if (e.shiftKey) redo(); else undo();
      return;
    }
    if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); return; }
    switch (e.key.toLowerCase()) {
      case "b": setTool("pen"); break;
      case "e": setTool("eraser"); break;
      case "f": setTool("fill"); break;
      case "i": setTool("picker"); break;
    }
  });

  // ---- Init ----
  newBoard(null);
  setColor(state.color);
  render();
})();
