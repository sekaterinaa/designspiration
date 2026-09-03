/**
 * TextOrbit
 * Runs a word around a ring in 3D. Whatever element you mark with
 * [data-object] stays at the centre at z = 0, so letters on the far side of
 * the circle pass behind it and letters on the near side pass in front.
 *
 *   <div id="ring" data-text="DYNAMIC" data-repeat="3">
 *     <div data-object><!-- your object --></div>
 *   </div>
 *   new TextOrbit('#ring');
 */
class TextOrbit {
  static defaults = {
    text: 'YOUR SOFTWARE GROWS WITH YOU',
    repeat: 1,            // times the text goes round the ring
    separator: ' • ',     // set '' to butt the repeats together
    speed: 0.22,          // degrees per 60fps frame
    tilt: -7,             // ring tilt in degrees
    spread: 1,            // >1 opens gaps between letters, <1 crowds them
    depth: 26,            // extrusion slices per letter
    band: 3,              // slices per colour stripe
    objectScale: 0.8,     // centre object size, relative to ring radius
    maxRadius: 0.46,      // biggest the ring may get, as a fraction of the stage
    arc: 0.4,             // share of the text that should read across the stage
    sensitivity: 0.3,     // degrees of spin per pixel dragged
    friction: 0.94,
    // Chromatic stripes down the extruded sides, front-most first.
    stripes: ['#ff2e9f', '#ffd62b', '#22d3ee', '#ff7a29', '#ffffff', '#4ade80'],
  };

  constructor(el, options = {}) {
    this.el = typeof el === 'string' ? document.querySelector(el) : el;
    if (!this.el) throw new Error('TextOrbit: element not found');

    this.opts = { ...TextOrbit.defaults, ...this.#readDataset(), ...options };
    this.reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    this.rot = 0;
    this.vel = 0;
    this.dragging = false;

    // Keep whatever the author put in the middle; everything else is ours.
    this.object = this.el.querySelector('[data-object]');
    this.el.innerHTML = '';

    this.world = document.createElement('div');
    this.world.className = 'orbit__world';
    this.world.style.setProperty('--tilt', `${this.opts.tilt}deg`);

    this.ring = document.createElement('div');
    this.ring.className = 'orbit__ring';

    this.world.append(this.ring);
    if (this.object) this.world.append(this.object);
    this.el.append(this.world);

    this.setText(this.opts.text);
    this.#bind();
    this.#loop();

    document.fonts?.ready.then(() => this.#layout());
  }

  /* ---------------------------------------------------------- public API */

  /** Swap the word without rebuilding the component. */
  setText(text) {
    this.opts.text = text;
    this.#buildChars();
    this.#layout();
  }

  destroy() {
    cancelAnimationFrame(this.raf);
    this.cleanup.forEach((fn) => fn());
    this.el.innerHTML = '';
  }

  /* --------------------------------------------------------------- build */

  #readDataset() {
    const d = this.el.dataset;
    const out = {};
    if (d.text) out.text = d.text;
    if (d.repeat) out.repeat = parseInt(d.repeat, 10);
    if (d.separator !== undefined) out.separator = d.separator;
    if (d.speed) out.speed = parseFloat(d.speed);
    if (d.tilt) out.tilt = parseFloat(d.tilt);
    if (d.spread) out.spread = parseFloat(d.spread);
    if (d.depth) out.depth = parseInt(d.depth, 10);
    return out;
  }

  #buildChars() {
    this.ring.innerHTML = '';
    const unit = this.opts.text + this.opts.separator;
    const run = unit.repeat(Math.max(1, this.opts.repeat));

    this.chars = [...run].map((ch) => {
      const el = document.createElement('div');
      el.className = 'char';
      el.setAttribute('aria-hidden', 'true');

      // Slices run back-to-front so the nearest paints last.
      for (let i = this.opts.depth; i >= 1; i--) {
        const slice = document.createElement('span');
        slice.className = 'char__slice';
        slice.style.setProperty('--i', i);
        slice.style.color = this.#stripe(i);
        slice.textContent = ch;
        el.append(slice);
      }

      const face = document.createElement('span');
      face.className = 'char__face';
      face.textContent = ch;
      el.append(face);

      this.ring.append(el);
      return el;
    });

    // The ring is decorative; expose the word once to assistive tech.
    this.el.setAttribute('role', 'img');
    this.el.setAttribute('aria-label', this.opts.text);
  }

  #stripe(i) {
    const { stripes, band } = this.opts;
    return stripes[Math.floor((i - 1) / band) % stripes.length];
  }

  /**
   * Give every letter an arc proportional to how wide it actually is, so
   * spacing round the rim stays even instead of stepping by a fixed angle.
   */
  #layout() {
    if (!this.chars?.length) return;

    this.el.style.setProperty('--type-scale', 1);
    const widths = this.chars.map((c) => c.offsetWidth);
    const total = widths.reduce((a, b) => a + b, 0);
    if (!total) return;

    // The text wraps the circumference exactly once: 2πr = total width.
    const raw = (total * this.opts.spread) / (2 * Math.PI);

    // Letter arcs are proportional to glyph widths, so scaling the type
    // scales the radius by the same factor and leaves the angles untouched.
    // That lets a single scale satisfy both fits below.
    const box = this.el.getBoundingClientRect();
    const stage = this.el.closest('.stage') || this.el;
    const persp = parseFloat(getComputedStyle(stage).perspective) || 760;

    // 1. The ring itself has to fit the stage.
    const limit = Math.max(140, Math.min(box.width, box.height) * this.opts.maxRadius);
    let fit = Math.min(1, limit / raw);

    // 2. The front of the ring is magnified by perspective, so a long phrase
    //    can still overflow sideways with only a few letters legible. Shrink
    //    until the readable front arc spans the stage rather than overrunning
    //    it. Magnification falls as the type shrinks, so this converges.
    const want = box.width * 0.86;
    for (let i = 0; i < 8; i++) {
      const r = raw * fit;
      const mag = persp / Math.max(persp - r, persp * 0.3);
      const front = total * this.opts.spread * fit * this.opts.arc * mag;
      if (front <= want) break;
      fit *= want / front;
    }

    this.el.style.setProperty('--type-scale', fit.toFixed(4));
    const radius = raw * fit;
    this.radius = radius;

    let walked = 0;
    this.angles = this.chars.map((c, i) => {
      const angle = ((walked + widths[i] / 2) / total) * 360;
      c.style.setProperty('--a', `${angle}deg`);
      c.style.setProperty('--r', `${radius}px`);
      walked += widths[i];
      return angle;
    });

    if (this.object) {
      this.object.style.setProperty(
        '--object-size', `${Math.round(radius * this.opts.objectScale)}px`
      );
    }
  }

  /* -------------------------------------------------------------- input */

  #bind() {
    this.cleanup = [];
    const on = (t, type, fn, opts) => {
      t.addEventListener(type, fn, opts);
      this.cleanup.push(() => t.removeEventListener(type, fn, opts));
    };

    const stage = this.el.closest('.stage') || this.el;
    let startX = 0, startRot = 0, lastX = 0, lastT = 0, id = null;

    on(stage, 'pointerdown', (e) => {
      if (e.button) return;
      id = e.pointerId;
      stage.setPointerCapture(id);
      this.dragging = true;
      stage.classList.add('is-dragging');
      startX = lastX = e.clientX;
      startRot = this.rot;
      lastT = performance.now();
      this.vel = 0;
    });

    on(stage, 'pointermove', (e) => {
      if (!this.dragging) return;
      this.rot = startRot + (e.clientX - startX) * this.opts.sensitivity;
      const now = performance.now();
      const dt = Math.max(now - lastT, 1);
      this.vel = ((e.clientX - lastX) * this.opts.sensitivity / dt) * 16.7;
      lastX = e.clientX;
      lastT = now;
    });

    const release = () => {
      if (!this.dragging) return;
      this.dragging = false;
      stage.classList.remove('is-dragging');
      if (id !== null && stage.hasPointerCapture?.(id)) stage.releasePointerCapture(id);
      id = null;
      if (performance.now() - lastT > 90) this.vel = 0;
      this.vel = Math.max(-18, Math.min(18, this.vel));
    };

    on(stage, 'pointerup', release);
    on(stage, 'pointercancel', release);
    on(stage, 'lostpointercapture', release);
    on(window, 'resize', () => this.#layout());
  }

  /* -------------------------------------------------------------- frame */

  #loop() {
    let last = performance.now();
    const frame = (now) => {
      // Motion is written per 60fps frame, then scaled by dt so it runs at
      // the same rate on a 120Hz display and a struggling one.
      const dt = Math.min(3, Math.max(0.4, (now - last) / (1000 / 60)));
      last = now;

      if (!this.dragging) {
        if (Math.abs(this.vel) > 0.02) {
          this.rot += this.vel * dt;
          this.vel *= Math.pow(this.opts.friction, dt);
        } else if (!this.reduced) {
          this.rot -= this.opts.speed * dt;
        }
      }

      this.ring.style.setProperty('--rot', `${this.rot.toFixed(3)}deg`);

      // Fade the far half of the ring so it reads as depth rather than
      // competing with the letters nearest the camera.
      if (this.angles) {
        for (let i = 0; i < this.chars.length; i++) {
          const facing = Math.cos((this.angles[i] + this.rot) * Math.PI / 180);
          this.chars[i].style.setProperty('--front', Math.max(0, facing).toFixed(3));
        }
      }

      this.raf = requestAnimationFrame(frame);
    };
    this.raf = requestAnimationFrame(frame);
  }
}

if (typeof module !== 'undefined' && module.exports) module.exports = TextOrbit;
