/* Pixel Doodle — a Magna-Doodle-style hexagonal pixel art tool */
(() => {
  "use strict";

  const canvas = document.getElementById("board");
  const ctx = canvas.getContext("2d");
  const CSS_SIZE = canvas.width; // internal pixel resolution (square)
  const SCREEN_BASE = "#dfe3e6";

  // ---- Hex grid geometry (flat-top hexagons, "odd-q" column offset) ----
  const SQRT3 = Math.sqrt(3);
  const COLS = 16;
  const ROWS = 14;

  // Pick the largest hex radius that lets COLS columns / ROWS rows fit
  // inside the square canvas, then center whichever axis has slack.
  const sizeFromWidth = CSS_SIZE / (2 + 1.5 * (COLS - 1));
  const sizeFromHeight = CSS_SIZE / (SQRT3 * (ROWS + 0.5));
  const HEX = Math.min(sizeFromWidth, sizeFromHeight);
  const GRID_W = 2 * HEX + 1.5 * HEX * (COLS - 1);
  const GRID_H = SQRT3 * HEX * (ROWS + 0.5);
  const ORIGIN_X = (CSS_SIZE - GRID_W) / 2 + HEX;
  const ORIGIN_Y = (CSS_SIZE - GRID_H) / 2 + (SQRT3 * HEX) / 2;

  const DIRS = [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]];

  function hexCenter(col, row) {
    const x = ORIGIN_X + HEX * 1.5 * col;
    const y = ORIGIN_Y + HEX * SQRT3 * row + (col & 1 ? (HEX * SQRT3) / 2 : 0);
    return [x, y];
  }

  function cubeRound(x, y, z) {
    let rx = Math.round(x), ry = Math.round(y), rz = Math.round(z);
    const dx = Math.abs(rx - x), dy = Math.abs(ry - y), dz = Math.abs(rz - z);
    if (dx > dy && dx > dz) rx = -ry - rz;
    else if (dy > dz) ry = -rx - rz;
    else rz = -rx - ry;
    return [rx, ry, rz];
  }

  // ---- State ----
  const state = {
    tool: "pen",
    color: "#111111",
    showGrid: true,
    pixels: [],        // flat array (row * COLS + col) of color strings or null
    drawing: false,
    lastCell: -1,
    eraseHigh: 0,      // 0..1, furthest the eraser slider has swept
  };

  const undoStack = [];
  const redoStack = [];

  function newBoard(fill = null) {
    state.pixels = new Array(COLS * ROWS).fill(fill);
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
  function drawHexPath(cx, cy) {
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const angle = (Math.PI / 180) * 60 * i;
      const px = cx + HEX * Math.cos(angle);
      const py = cy + HEX * Math.sin(angle);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.closePath();
  }

  function render() {
    ctx.clearRect(0, 0, CSS_SIZE, CSS_SIZE);
    ctx.fillStyle = SCREEN_BASE;
    ctx.fillRect(0, 0, CSS_SIZE, CSS_SIZE);

    for (let row = 0; row < ROWS; row++) {
      for (let col = 0; col < COLS; col++) {
        const idx = row * COLS + col;
        const [cx, cy] = hexCenter(col, row);
        drawHexPath(cx, cy);
        ctx.fillStyle = state.pixels[idx] || SCREEN_BASE;
        ctx.fill();
        if (state.showGrid) {
          ctx.strokeStyle = "rgba(0,0,0,0.1)";
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }
    }
  }

  // ---- Coordinate mapping: pixel -> hex (axial, cube-rounded) ----
  function cellFromEvent(e) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = CSS_SIZE / rect.width;
    const scaleY = CSS_SIZE / rect.height;
    const px = (e.clientX - rect.left) * scaleX - ORIGIN_X;
    const py = (e.clientY - rect.top) * scaleY - ORIGIN_Y;

    const qFrac = (2 / 3 * px) / HEX;
    const rFrac = ((-1 / 3) * px + (SQRT3 / 3) * py) / HEX;
    const [rx, , rz] = cubeRound(qFrac, -qFrac - rFrac, rFrac);

    const col = rx;
    const row = rz + (rx - (rx & 1)) / 2;
    if (col < 0 || col >= COLS || row < 0 || row >= ROWS) return -1;
    return row * COLS + col;
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

  function floodFill(startIdx) {
    const target = state.pixels[startIdx];
    const replacement = state.color;
    if (target === replacement) return;

    const startCol = startIdx % COLS;
    const startRow = Math.floor(startIdx / COLS);
    const startQ = startCol;
    const startR = startRow - (startCol - (startCol & 1)) / 2;

    const stack = [[startQ, startR]];
    while (stack.length) {
      const [q, r] = stack.pop();
      const col = q;
      const row = r + (q - (q & 1)) / 2;
      if (col < 0 || col >= COLS || row < 0 || row >= ROWS) continue;
      const idx = row * COLS + col;
      if (state.pixels[idx] !== target) continue;
      state.pixels[idx] = replacement;
      for (const [dq, dr] of DIRS) stack.push([q + dq, r + dr]);
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
    const upTo = Math.floor(frac * COLS);
    for (let c = 0; c < upTo; c++) {
      for (let r = 0; r < ROWS; r++) {
        state.pixels[r * COLS + c] = null;
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
