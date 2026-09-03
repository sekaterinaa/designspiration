# Text Orbit

A word running around a 3D ring, passing **behind** whatever object sits at the
centre. Chunky glossy type with chromatic striped extrusion.

No dependencies, no build step. Open `index.html`.

![preview](docs/orbit.jpg)

## Dropping in your own object

The centre object is yours — the component keeps whatever you mark with
`[data-object]` and builds the ring around it:

```html
<div class="orbit" data-text="DYNAMIC" data-repeat="3">
  <div class="orbit__object" data-object>
    <img src="floppy.png" alt="" />
  </div>
</div>
```

```js
new TextOrbit('.orbit');
```

The slot is pinned at `z = 0`, the letters sit at `±radius`, and all of them
share one `preserve-3d` context — so the browser sorts them by depth on its own.
Letters on the far side of the circle are drawn behind your object, letters on
the near side in front, with no z-index bookkeeping. The component sets
`--object-size` on the slot from the ring radius; ignore it and size the object
yourself if you'd rather.

## How the type is built

Each letter is a stack of ~26 copies of itself, each pushed a little further back
in Z. The slices cycle through a stripe palette (`band` slices per colour), which
is what produces the chromatic extruded sides:

```js
stripes: ['#ff2e9f', '#ffd62b', '#22d3ee', '#ff7a29', '#ffffff', '#4ade80']
```

Letters are placed round the rim with an arc proportional to each glyph's real
width, so spacing stays even instead of stepping by a fixed angle. The radius
follows from the text itself — the run of letters wraps the circumference exactly
once:

```
radius = totalTextWidth * spread / 2π
```

So a longer word, more repeats, or a bigger font all grow the ring.

### One thing to know if you edit this

Nothing may set `opacity` or `filter` on `.char`. Either property flattens the
`preserve-3d` context and collapses that letter's extrusion into a single plane.
The far half of the ring is faded through a `--front` custom property that JS
writes on each letter per frame, which the **leaf** elements read.

## Options

Pass as a second argument, or as `data-` attributes (`data-text`, `data-repeat`,
`data-separator`, `data-speed`, `data-tilt`, `data-spread`, `data-depth`):

| Option | Default | What it does |
| --- | --- | --- |
| `text` | `'DYNAMIC'` | The orbiting word |
| `repeat` | `3` | Times the word goes round the ring |
| `separator` | `' • '` | Set `''` to butt the repeats together |
| `speed` | `0.22` | Degrees per frame |
| `tilt` | `-7` | Ring tilt in degrees |
| `spread` | `1` | `>1` opens gaps between letters, `<1` crowds them |
| `depth` | `26` | Extrusion slices per letter |
| `band` | `3` | Slices per colour stripe |
| `objectScale` | `0.8` | Centre object size, relative to ring radius |
| `stripes` | 6 colours | The extrusion palette |

Methods: `setText(word)` swaps the word and re-lays the ring without a rebuild;
`destroy()` tears it down.

Drag to spin with momentum; let go and it resumes its own rotation. Motion is
delta-time normalised, so it runs at the same rate on 60Hz and 120Hz, and
`prefers-reduced-motion: reduce` stops the idle spin.

## Styling

Colours and type live in custom properties at the top of `orbit.css`: `--cream`
for the ground, `--face-top` / `--face-mid` / `--face-bottom` for the glossy
letter faces, `--depth-step` for how far the extrusion reaches, `--type-size` for
the letters, and `--letterbox` for the black bars.

## Also in here

`glass-carousel.html` is an earlier take — a rotating cylinder of frosted-glass
panels carrying extruded 3D words. Same extrusion technique, different world.

![glass carousel](docs/glass-carousel.jpg)

## Browser support

Needs `transform-style: preserve-3d` — Chrome/Edge, Safari 16+, Firefox. Depth
sorting between the ring and the centre object relies on the browser compositing
one shared 3D context, which all current engines do.
