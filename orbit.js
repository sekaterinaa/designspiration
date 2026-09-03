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
    repeat: 2,            // times the text goes round the ring
    separator: ' • ',     // set '' to butt the repeats together
    sweep: 360,           // degrees of the circle the text occupies
    speed: 0.22,          // degrees per 60fps frame
    start: -22,           // opening rotation, for an asymmetric first frame
    tilt: -7,             // ring tilt in degrees
    spread: 1,            // >1 opens gaps between letters, <1 crowds them
    depth: 26,            // extrusion slices per letter
    band: 3,              // slices per colour stripe
    objectScale: 0.55,    // centre object size, relative to ring radius
    ringScale: 0.55,      // ring radius, as a fraction of the stage
    maxScale: 1.4,        // ceiling on type scale, so short text can't balloon
    perspective: 3,       // perspective distance, as a multiple of the radius
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

    this.rot = this.opts.start;
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
    if (d.sweep) out.sweep = parseFloat(d.sweep);
    if (d.speed) out.speed = parseFloat(d.speed);
    if (d.tilt) out.tilt = parseFloat(d.tilt);
    if (d.spread) out.spread = parseFloat(d.spread);
    if (d.depth) out.depth = parseInt(d.depth, 10);
    return out;
  }

  #buildChars() {
    this.ring.innerHTML = '';
    const n = Math.max(1, this.opts.repeat);
    // A full circle closes on itself, so it needs a separator after the last
    // repeat too; a partial sweep has two loose ends and does not.
    const run = this.opts.sweep >= 360
      ? (this.opts.text + this.opts.separator).repeat(n)
      : Array(n).fill(this.opts.text).join(this.opts.separator);

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

    // The ring size is a stage-relative design choice; the length of arc it
    // offers then sets the type size. (Deriving the radius from the text
    // instead would pin the type to whatever the phrase happened to need.)
    const stage = this.el.closest('.stage') || this.el;
    const box = stage.getBoundingClientRect();
    const sweep = (this.opts.sweep * Math.PI) / 180;
    let radius = Math.max(120, Math.min(box.width, box.height * 1.9) * this.opts.ringScale);

    let fit = (radius * sweep) / (total * this.opts.spread);
    if (fit > this.opts.maxScale) {
      // Short text would otherwise blow up to fill the arc. Hold the type and
      // pull the ring in instead, which keeps the sweep exact.
      fit = this.opts.maxScale;
      radius = (total * this.opts.spread * fit) / sweep;
    }

    this.el.style.setProperty('--type-scale', fit.toFixed(4));
    this.radius = radius;

    // Tie the camera to the ring so the nearest letters are magnified by the
    // same amount whatever size the ring ends up.
    stage.style.perspective = `${Math.round(radius * this.opts.perspective)}px`;

    // Centre the run on the front of the ring, so it starts readable and
    // sweeps behind the object as it turns.
    let walked = 0;
    this.angles = this.chars.map((c, i) => {
      const angle = -this.opts.sweep / 2
        + ((walked + widths[i] / 2) / total) * this.opts.sweep;
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
