/* Pixel Doodle — a Magna-Doodle-style pixel art tool */
(() => {
  "use strict";

  const canvas = document.getElementById("board");
  const ctx = canvas.getContext("2d");
  const CSS_SIZE = canvas.width; // internal pixel resolution (square)
  const SCREEN_BASE = "#dfe3e6";

  // ---- State ----
  const state = {
    grid: 16,
    tool: "pen",
    color: "#111111",
    showGrid: true,
    pixels: [],        // flat array of color strings or null
    drawing: false,
    lastCell: -1,
    eraseHigh: 0,      // 0..1, furthest the eraser slider has swept
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

    ctx.fillStyle = SCREEN_BASE;
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

  // ---- Pointer events (drawing) ----
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

  // ---- Sliding eraser (mimics the real toy's wipe bar) ----
  const eraseTrack = document.getElementById("eraseTrack");
  const eraseThumb = document.getElementById("eraseThumb");
  let sweeping = false;

  function setThumb(frac) {
    eraseThumb.style.left = (frac * 100) + "%";
    eraseThumb.setAttribute("aria-valuenow", Math.round(frac * 100));
  }

  function sweepTo(frac) {
    if (frac <= state.eraseHigh) return;
    state.eraseHigh = frac;
    const col = Math.floor(frac * state.grid);
    for (let c = 0; c < col; c++) {
      for (let r = 0; r < state.grid; r++) {
        state.pixels[r * state.grid + c] = null;
      }
    }
    render();
  }

  function moveThumb(frac) {
    frac = Math.max(0, Math.min(1, frac));
    eraseThumb.classList.remove("snapping");
    setThumb(frac);
    sweepTo(frac);
    if (frac >= 0.96) {
      eraseThumb.classList.add("snapping");
      setTimeout(() => {
        newBoard(null);
        state.eraseHigh = 0;
        setThumb(0);
        render();
      }, 350);
    }
  }

  function fracFromEvent(e) {
    const rect = eraseTrack.getBoundingClientRect();
    return (e.clientX - rect.left) / rect.width;
  }

  eraseThumb.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    try { eraseThumb.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
    pushUndo();
    sweeping = true;
  });
  eraseThumb.addEventListener("pointermove", (e) => {
    if (!sweeping) return;
    moveThumb(fracFromEvent(e));
  });
  const endSweep = () => { sweeping = false; };
  eraseThumb.addEventListener("pointerup", endSweep);
  eraseThumb.addEventListener("pointercancel", endSweep);

  eraseThumb.addEventListener("keydown", (e) => {
    const step = 0.08;
    if (e.key === "ArrowRight" || e.key === "ArrowUp") {
      e.preventDefault();
      pushUndo();
      moveThumb((state.eraseHigh || 0) + step);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
      e.preventDefault();
      setThumb(Math.max(0, (state.eraseHigh || 0) - step));
    }
  });

  // ---- Stamps: quick ink colors, styled after the toy's rubber stamps ----
  document.querySelectorAll(".stamp, .letter-bubble").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.color = btn.dataset.color;
      state.tool = "pen";
    });
  });

  // ---- Stylus: switches back to the pen tool ----
  document.getElementById("stylusBtn").addEventListener("click", () => {
    state.tool = "pen";
  });

  // Keyboard shortcuts: B pen, E eraser, F fill, I eyedropper, Ctrl/Cmd Z undo/redo
  window.addEventListener("keydown", (e) => {
    if (document.activeElement === eraseThumb) return;
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
