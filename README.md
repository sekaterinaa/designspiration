# Pixel Doodle 🎨

A browser-based **pixel art drawing tool** styled like a classic **Magna Doodle** —
draw on the grid with your mouse and hit **Shake to erase** to wipe the screen clean.

No build step, no dependencies. Just open `index.html` in a browser.

## Features

- **Dashboard layout** — tools on the left, the Magna Doodle canvas in the middle, actions on the right.
- **Drawing tools** — Pen, Eraser, Fill (flood fill), and Eyedropper.
- **Color palette** — 12 preset swatches plus a custom color picker.
- **Adjustable grid** — 8×8 up to 48×48, with optional grid lines. Existing art is resampled when you resize.
- **Shake to erase** — the knob shakes the whole frame and clears the board, just like the real toy.
- **Undo / Redo** — full history (also `Ctrl/⌘ Z` and `Ctrl/⌘ Shift Z`).
- **Export** — download your art as a crisp PNG at 1× / 8× / 16× / 32× scale.

## Keyboard shortcuts

| Key | Action |
| --- | ------ |
| `B` | Pen |
| `E` | Eraser |
| `F` | Fill |
| `I` | Eyedropper |
| `Ctrl/⌘ Z` | Undo |
| `Ctrl/⌘ Shift Z` / `Ctrl/⌘ Y` | Redo |

## Run it

```bash
# just open the file
open index.html          # macOS
xdg-open index.html      # Linux

# or serve it locally
python3 -m http.server 8000
# then visit http://localhost:8000
```

## Files

- `index.html` — markup and layout
- `style.css` — theme and the Magna Doodle frame
- `app.js` — canvas drawing engine, tools, history, and export
