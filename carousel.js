/**
 * GlassTextCarousel
 * A 3D rotating cylinder of frosted-glass panels, each carrying an
 * extruded 3D word instead of an image.
 *
 *   new GlassTextCarousel(el, { words: ['DESIGN', 'MOTION'] })
 *
 * Options can also be supplied via data attributes on the element:
 *   data-words="DESIGN, MOTION, GLASS"   data-autoplay="true"   data-tilt="9"
 */
class GlassTextCarousel {
  static defaults = {
    words: ['DESIGN', 'MOTION', 'GLASS', 'DEPTH', 'LIGHT', 'RHYTHM'],
    autoplay: true,
    autoSpeed: 0.09,      // degrees per frame while idling
    tilt: 9,              // camera tilt in degrees
    gap: 1.22,            // >1 pushes panels further from the axis
    depth: 38,            // extrusion slices behind each letterform
    sensitivity: 0.34,    // degrees of spin per pixel dragged
    friction: 0.945,      // inertia decay
    idleDelay: 2600,      // ms of stillness before autoplay resumes
  };

  constructor(el, options = {}) {
    this.el = typeof el === 'string' ? document.querySelector(el) : el;
    if (!this.el) throw new Error('GlassTextCarousel: element not found');

    this.opts = { ...GlassTextCarousel.defaults, ...this.#readDataset(), ...options };

    this.reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (this.reduced) this.opts.autoplay = false;
    if (window.innerWidth < 520) this.opts.depth = Math.min(this.opts.depth, 22);

    this.words = this.opts.words;
    this.count = this.words.length;
    this.step = 360 / this.count;

    this.rot = 0;            // current ring rotation, degrees
    this.vel = 0;            // inertial velocity, degrees per frame
    this.target = null;      // snap target, degrees
    this.dragging = false;
    this.hovered = false;
    this.lastInput = 0;
    this.index = -1;
    this.listeners = [];

    this.#build();
    this.#bind();
    this.#measure();
    this.#loop();

    // Web fonts change the metrics, so re-fit once they land.
    document.fonts?.ready.then(() => this.#measure());
  }

  /* ---------------------------------------------------------- public API */

  onChange(fn) {
    this.listeners.push(fn);
    if (this.index >= 0) fn(this.index, this.words[this.index]);
    return this;
  }

  /** Rotate to a specific panel by index, taking the shortest way round. */
  goTo(index) {
    const desired = -index * this.step;
    const delta = this.#shortest(desired - this.rot);
    this.#interact();
    this.vel = 0;
    this.target = this.rot + delta;
  }

  next() { this.goTo(this.index + 1); }
  prev() { this.goTo(this.index - 1); }

  destroy() {
    cancelAnimationFrame(this.raf);
    this.cleanup.forEach((fn) => fn());
    this.el.innerHTML = '';
  }

  /* ------------------------------------------------------------- build */

  #readDataset() {
    const d = this.el.dataset;
    const out = {};
    if (d.words) out.words = d.words.split(',').map((w) => w.trim()).filter(Boolean);
    if (d.autoplay) out.autoplay = d.autoplay !== 'false';
    if (d.tilt) out.tilt = parseFloat(d.tilt);
    if (d.gap) out.gap = parseFloat(d.gap);
    if (d.depth) out.depth = parseInt(d.depth, 10);
    return out;
  }

  #build() {
    this.el.innerHTML = '';
    this.el.tabIndex = 0;
    this.el.setAttribute('role', 'group');
    this.el.setAttribute('aria-roledescription', 'carousel');
    this.el.setAttribute('aria-label', '3D rotating text carousel');

    this.stage = document.createElement('div');
    this.stage.className = 'stage';
    this.stage.style.setProperty('--tilt', `${this.opts.tilt}deg`);

    this.ring = document.createElement('div');
    this.ring.className = 'stage__ring';

    const floor = document.createElement('div');
    floor.className = 'stage__floor';

    this.panels = this.words.map((word, i) => this.#panel(word, i));
    this.ring.append(...this.panels);
    this.stage.append(this.ring, floor);
    this.el.append(this.stage);
  }

  #panel(word, i) {
    const panel = document.createElement('div');
    panel.className = 'panel';
    panel.style.setProperty('--angle', i * this.step);

    const glass = document.createElement('div');
    glass.className = 'panel__glass';
    const sheen = document.createElement('span');
    sheen.className = 'panel__sheen';
    glass.append(sheen);

    const rim = document.createElement('div');
    rim.className = 'panel__rim';

    const tag = document.createElement('div');
    tag.className = 'panel__tag';
    tag.textContent = 'glass';

    const num = document.createElement('div');
    num.className = 'panel__index';
    num.textContent = String(i + 1).padStart(2, '0');

    const word3d = this.#word(word);
    panel.append(glass, rim, tag, num, word3d);
    panel._word = word3d;
    return panel;
  }

  /** Builds one word as a stack of z-offset slices — a real extrusion. */
  #word(word) {
    const wrap = document.createElement('div');
    wrap.className = 'word';

    const stack = document.createElement('div');
    stack.className = 'word__stack';
    stack.style.setProperty('--text-depth', this.opts.depth);

    // Back-to-front so the nearest slices paint last.
    for (let i = this.opts.depth; i >= 1; i--) {
      const layer = document.createElement('span');
      layer.className = 'word__layer';
      layer.style.setProperty('--i', i);
      layer.setAttribute('aria-hidden', 'true');
      layer.textContent = word;
      stack.append(layer);
    }

    const face = document.createElement('span');
    face.className = 'word__face';
    face.textContent = word;
    stack.append(face);

    wrap.append(stack);
    wrap._stack = stack;
    wrap._face = face;
    return wrap;
  }

  /* -------------------------------------------------------------- input */

  #bind() {
    this.cleanup = [];
    const on = (target, type, fn, opts) => {
      target.addEventListener(type, fn, opts);
      this.cleanup.push(() => target.removeEventListener(type, fn, opts));
    };

    let startX = 0;
    let startRot = 0;
    let lastX = 0;
    let lastT = 0;
    let pointerId = null;

    on(this.el, 'pointerdown', (e) => {
      if (e.button !== undefined && e.button !== 0) return;
      pointerId = e.pointerId;
      this.el.setPointerCapture(pointerId);
      this.dragging = true;
      this.el.classList.add('is-dragging');
      startX = lastX = e.clientX;
      startRot = this.rot;
      lastT = performance.now();
      this.vel = 0;
      this.target = null;
      this.#interact();
    });

    on(this.el, 'pointermove', (e) => {
      if (!this.dragging) return;
      this.rot = startRot + (e.clientX - startX) * this.opts.sensitivity;

      const now = performance.now();
      const dt = Math.max(now - lastT, 1);
      // convert px/ms into degrees per 16.7ms frame
      this.vel = ((e.clientX - lastX) * this.opts.sensitivity / dt) * 16.7;
      lastX = e.clientX;
      lastT = now;
      this.#interact();
    });

    const release = () => {
      if (!this.dragging) return;
      this.dragging = false;
      this.el.classList.remove('is-dragging');
      if (pointerId !== null && this.el.hasPointerCapture?.(pointerId)) {
        this.el.releasePointerCapture(pointerId);
      }
      pointerId = null;
      // A stale velocity from a long pause before release feels wrong.
      if (performance.now() - lastT > 90) this.vel = 0;
      this.vel = Math.max(-14, Math.min(14, this.vel));
      if (Math.abs(this.vel) < 0.4) { this.vel = 0; this.#snap(); }
      this.#interact();
    };

    on(this.el, 'pointerup', release);
    on(this.el, 'pointercancel', release);
    on(this.el, 'lostpointercapture', release);

    let wheelTimer = null;
    on(this.el, 'wheel', (e) => {
      const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      if (!delta) return;
      e.preventDefault();
      this.target = null;
      this.rot -= delta * 0.16;
      this.vel = 0;
      this.#interact();
      clearTimeout(wheelTimer);
      wheelTimer = setTimeout(() => this.#snap(), 120);
    }, { passive: false });

    on(this.el, 'keydown', (e) => {
      if (e.key === 'ArrowLeft') { e.preventDefault(); this.prev(); }
      if (e.key === 'ArrowRight') { e.preventDefault(); this.next(); }
    });

    on(this.el, 'pointerenter', () => { this.hovered = true; });
    on(this.el, 'pointerleave', () => { this.hovered = false; });
    on(window, 'resize', () => this.#measure());
  }

  #interact() { this.lastInput = performance.now(); }

  #snap() {
    const nearest = Math.round(this.rot / this.step) * this.step;
    this.target = nearest;
  }

  #shortest(delta) {
    return delta - 360 * Math.round(delta / 360);
  }

  /* -------------------------------------------------------------- frame */

  #measure() {
    const panel = this.panels[0];
    const w = panel.offsetWidth || parseFloat(getComputedStyle(panel).width);
    // Radius that seats N panels of width w around a cylinder, plus breathing room.
    this.radius = (w / 2) / Math.tan(Math.PI / this.count) * this.opts.gap;
    this.el.style.setProperty('--radius', `${this.radius}px`);
    this.panels.forEach((p) => p.style.setProperty('--radius', `${this.radius}px`));
    this.#fit();
  }

  /** Shrink any word that would run past the edge of its glass card. */
  #fit() {
    for (const panel of this.panels) {
      const { _stack: stack, _face: face } = panel._word;
      stack.style.fontSize = '';
      const base = parseFloat(getComputedStyle(stack).fontSize);
      // Type floats in front of the card, so it foreshortens less than the
      // card does when a panel turns. Budget under the full width to stop
      // words hanging off the edge at an angle.
      const avail = panel.clientWidth * 0.8;
      const natural = face.offsetWidth;
      if (!natural || !avail) continue;
      const ratio = Math.min(1, avail / natural);
      if (ratio < 1) stack.style.fontSize = `${(base * ratio).toFixed(2)}px`;
    }
  }

  #loop() {
    let last = performance.now();
    const frame = (now) => {
      // Everything below is expressed per 60fps frame, then scaled by dt so
      // a 120Hz display and a stuttering one move at the same rate.
      const dt = Math.min(3, Math.max(0.4, (now - last) / (1000 / 60)));
      last = now;
      this.#advance(dt);
      this.#render();
      this.raf = requestAnimationFrame(frame);
    };
    this.raf = requestAnimationFrame(frame);
  }

  #advance(dt) {
    if (this.dragging) return;

    if (Math.abs(this.vel) > 0.02) {
      this.rot += this.vel * dt;
      this.vel *= Math.pow(this.opts.friction, dt);
      if (Math.abs(this.vel) < 0.35) {
        this.vel = 0;
        this.#snap();
      }
      return;
    }

    if (this.target !== null) {
      const delta = this.target - this.rot;
      if (Math.abs(delta) < 0.03) {
        this.rot = this.target;
        this.target = null;
      } else {
        this.rot += delta * (1 - Math.pow(1 - 0.14, dt));
      }
      return;
    }

    const idle = performance.now() - this.lastInput > this.opts.idleDelay;
    if (this.opts.autoplay && idle && !this.hovered) {
      this.rot -= this.opts.autoSpeed * dt;
    }
  }

  #render() {
    this.ring.style.setProperty('--rot', `${this.rot}deg`);

    let bestIndex = 0;
    let bestFacing = -Infinity;

    for (let i = 0; i < this.count; i++) {
      const theta = (i * this.step + this.rot) * Math.PI / 180;
      const facing = Math.cos(theta);   // 1 = square to the camera, -1 = behind
      const front = Math.max(0, facing);

      if (facing > bestFacing) { bestFacing = facing; bestIndex = i; }

      // Only custom properties here — the panel itself must stay free of
      // opacity/filter so its preserve-3d context (and the extrusion) survives.
      const panel = this.panels[i];
      panel.style.setProperty('--facing', Math.sin(theta).toFixed(3));
      panel.style.setProperty('--front', front.toFixed(3));
    }

    if (bestIndex !== this.index) {
      this.index = bestIndex;
      this.listeners.forEach((fn) => fn(bestIndex, this.words[bestIndex]));
    }
  }
}

if (typeof module !== 'undefined' && module.exports) module.exports = GlassTextCarousel;
