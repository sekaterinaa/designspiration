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
      if (c) state.color = c;
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

  // Keyboard shortcuts: B pen, E eraser, F fill, I eyedropper, Ctrl/Cmd Z undo/redo
  window.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "z") {
      e.preventDefault();
      if (e.shiftKey) redo(); else undo();
      return;
    }
    if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); return; }
    switch (e.key.toLowerCase()) {
      case "b": state.tool = "pen"; break;
      case "e": state.tool = "eraser"; break;
      case "f": state.tool = "fill"; break;
      case "i": state.tool = "picker"; break;
    }
  });

  // ---- Init ----
  newBoard(null);
  render();
})();
