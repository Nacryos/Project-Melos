// Ordered (Bayer) dithering of a painting in one WebGL fragment pass.
// Every painting is uploaded once to its own texture. A transition ("ink blot to ripple")
// only decides, per dither cell, when that cell swaps from painting A to B. Each ink blot
// lands (at its own delay), flips its splash, and sends out its own ripple; a cell flips
// when the first wave reaches it, so ripples from separate blots meet along a seam where
// their crests add for a moment and then die. Cells no wave has reached are untouched,
// and the Bayer pattern never moves.
//
// Mosaic relief: each painting also has a depth map (near = bright). Tiles sample the
// painting shifted by their depth as the viewer moves (parallax), nearer tiles cast a short
// shadow down-right and catch a rim of light up-left, and every tile gets a slight random
// tilt, so figures read as set a touch proud of the ground like real tesserae.

const VS = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`;

const FS = `
precision highp float;
uniform sampler2D texA, texB, depA, depB;
uniform vec2 res, sizeA, sizeB, focA, focB, mouse;
uniform float cell, matrix, levels, spread, sat, con, bri, amount, lensR, palN;
uniform float t, seed, reach, glow;        // transition progress, per-transition seed, ripple extent, crest brightness
uniform vec4 epi[4];                       // ink blots: xy in aspect space, z = radius, w = landing delay
uniform float lensOn;
uniform vec2 view;                          // viewer offset, -1..1, eased
uniform float parallax, relief, tilt, grout, shadowLen;
uniform vec3 pal[8];

float b2(vec2 a){ a = floor(a); return fract(a.x * .5 + a.y * a.y * .75); }
float b4(vec2 a){ return b2(.5 * a) * .25 + b2(a); }
float b8(vec2 a){ return b4(.5 * a) * .25 + b2(a); }
float bayer(vec2 a){ return matrix > 6. ? b8(a) : matrix > 3. ? b4(a) : b2(a); }
float hash(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
float vnoise(vec2 p){
  vec2 i = floor(p), f = fract(p); f = f * f * (3. - 2. * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + 1.), f.x), f.y);
}

vec2 cover(vec2 uv, vec2 img, vec2 foc){
  float ra = res.x / res.y, ia = img.x / img.y;
  vec2 s = vec2(min(ra / ia, 1.), min(ia / ra, 1.));
  return clamp(foc, s * .5, 1. - s * .5) + (uv - .5) * s;
}
vec3 grade(vec3 c){
  c = (c - .5) * con + .5 + bri;
  float l = dot(c, vec3(.2126, .7152, .0722));
  return clamp(mix(vec3(l), c, sat), 0., 1.);
}
vec3 nearest(vec3 c){
  vec3 best = pal[0]; float bd = 1e9;
  for (int i = 0; i < 8; i++){
    if (float(i) >= palN) break;
    vec3 d = c - pal[i]; float dd = dot(d, d);
    if (dd < bd){ bd = dd; best = pal[i]; }
  }
  return best;
}
// Signed distance to one ink blot (negative inside). Edges are lobed by direction noise
// so blots read as splashes, not circles.
float blotField(vec2 p, vec4 e, float i){
  vec2 d = p - e.xy;
  float lobes = vnoise(normalize(d + 1e-5) * 2.2 + i * 5.3 + seed);
  float grain = vnoise(p * 18. + seed) * .25;
  return length(d) - e.z * (.55 + .8 * lobes + grain);
}
// x: how far (0..1) this cell has turned into B; y: ripple-crest brightness.
vec2 swap(vec2 uv, vec2 ix){
  if (t <= 0.) return vec2(0.);
  vec2 p = uv * vec2(res.x / res.y, 1.);
  float jitter = (vnoise(p * 6. + seed) - .5) * .06 + (hash(ix + seed) - .5) * .03;   // ragged, per-pixel front
  const float w = .07;
  float ts = 9., nearBlot = 9.;
  float tsi[4]; float amp[4];
  for (int i = 0; i < 4; i++){
    vec4 e = epi[i];
    if (e.z <= 0.) { tsi[i] = 9.; amp[i] = 0.; continue; }
    float f = blotField(p, e, float(i));
    // Splash flips fast from the middle out; beyond it the wave travels at one speed for every blot.
    float ti = f < 0. ? e.w + .12 * clamp(1. + f / e.z, 0., 1.)
                     : e.w + .12 + .74 * pow(clamp(f / reach, 0., 1.), .85) + jitter;
    tsi[i] = f < 0. ? 9. : ti;              // only the travelling wave carries a crest
    amp[i] = clamp(e.z / .08, .4, 1.);      // bigger splash, stronger wave
    ts = min(ts, ti);
    nearBlot = min(nearBlot, f);
  }
  if (nearBlot < .1 && hash(floor(ix * .5) + seed * 3.) < .06) ts = min(ts, epi[0].w + .08);   // spatter
  float k = smoothstep(ts, ts + w, t);
  // Superpose every wave whose front is here now; a front that arrives after the cell has
  // already flipped has collided with another wave and stops.
  float crest = 0.;
  for (int i = 0; i < 4; i++){
    if (tsi[i] > ts + .03) continue;
    crest += amp[i] * exp(-pow((t - tsi[i] - w * .5) / .035, 2.));
  }
  return vec2(k, min(crest, 1.8));
}
vec3 scene(vec2 uv, float k){
  vec3 a = texture2D(texA, cover(uv, sizeA, focA)).rgb;
  return k > 0. ? mix(a, texture2D(texB, cover(uv, sizeB, focB)).rgb, k) : a;
}
float depth(vec2 uv, float k){
  float a = texture2D(depA, cover(uv, sizeA, focA)).r;
  return k > 0. ? mix(a, texture2D(depB, cover(uv, sizeB, focB)).r, k) : a;
}

void main(){
  vec2 fc = gl_FragCoord.xy;
  vec2 ix = floor(fc / cell);
  float th = bayer(ix);
  vec2 uvc = (ix + .5) * cell / res;
  vec2 sw = swap(uvc, ix);

  // Mosaic relief, decided per tile so the dither stays crisp.
  float h = depth(uvc, sw.x);
  vec2 par = view * (h - .35) * parallax / res;                 // nearer tiles slide against the ground
  vec3 col = grade(scene(uvc + par, sw.x));
  vec2 L = vec2(-1., 1.) * shadowLen / res;                     // toward the light (up-left)
  float h1 = depth(uvc + L * .5, sw.x), h2 = depth(uvc + L, sw.x);
  float shadow = smoothstep(.03, .22, max(h1 - h, (h2 - h) * .75));   // a nearer tile blocks the light
  float rim = smoothstep(.03, .22, h - h1);                     // this tile's lit edge stands proud
  col *= 1. - relief * shadow;
  col += relief * .35 * rim * (1. - col);
  col *= 1. + (hash(ix * 1.37 + 3.1) - .5) * tilt;              // each tessera set at a slight angle
  col += sw.y * glow;

  vec3 d;
  if (palN > .5) d = nearest(col + (th - .5) * spread * .5);
  else { float L = levels - 1.; d = floor(col * L + th * spread + (1. - spread) * .5) / L; }

  if (grout > 0. && cell >= 4.) {                                // thin gaps between tesserae
    vec2 q = fract(fc / cell) * cell;
    d *= 1. - grout * .55 * step(min(q.x, q.y), .999);
  }

  float k = amount;
  if (lensOn > .5) k *= smoothstep(.8, 1., length(fc - mouse) / lensR);
  if (k >= 1.) { gl_FragColor = vec4(d, 1.); return; }   // skip the undithered pass when unseen
  vec3 orig = grade(scene(fc / res, sw.x));
  gl_FragColor = vec4(mix(orig, d, k), 1.);
}`;

export const PALETTES = {
  levels: null,
  aegean: ['#0f1c2e', '#244a73', '#5f8fb8', '#e9ecea', '#d9a33a', '#8a4b3c'],
  marble: ['#141a24', '#6b7480', '#c9cfd2', '#f3f5f4'],
  krokos: ['#1b1712', '#6e3b1f', '#d08a2e', '#f2d58a', '#f7f3ea'],
  lapis:  ['#0a1230', '#1d3a8a', '#5a7fd6', '#e8e6df', '#c9a44c'],
};

const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255);

export function createDither(canvas) {
  const gl = canvas.getContext('webgl', { antialias: false, powerPreference: 'high-performance' });
  if (!gl) return null;
  const sh = (type, src) => {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  };
  const prog = gl.createProgram();
  gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS));
  gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
  gl.linkProgram(prog); gl.useProgram(prog);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
  const U = {};
  for (let i = 0, n = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS); i < n; i++) {
    const name = gl.getActiveUniform(prog, i).name;
    U[name.replace('[0]', '')] = gl.getUniformLocation(prog, name);
  }
  gl.uniform1i(U.texA, 0); gl.uniform1i(U.texB, 1); gl.uniform1i(U.depA, 2); gl.uniform1i(U.depB, 3);

  const cache = new Map();   // key -> { tex, size, foc }
  // Upload (or re-upload a sharper copy of) an image into the key's texture.
  const texFrom = (tex, src) => {
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    if (src.width !== undefined && !(src instanceof HTMLImageElement))
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, src.data);
    else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR],
      [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]])
      gl.texParameteri(gl.TEXTURE_2D, k, v);
    return tex;
  };
  // Mid-grey 1x1 stands in until (or unless) a painting's depth map arrives: flat, no relief.
  const flat = texFrom(gl.createTexture(), { width: 1, data: new Uint8Array([90, 90, 90, 255]) });
  const upload = (key, img, foc) => {
    let s = cache.get(key);
    if (!s) { s = { tex: gl.createTexture(), dep: flat, foc: [foc[0], 1 - foc[1]] }; cache.set(key, s); }
    texFrom(s.tex, img);
    s.size = [img.naturalWidth, img.naturalHeight];
    if (s === A || s === B) request();
    return s;
  };
  // Sharper copies that arrive mid-transition wait for it to end: a big upload blocks a frame.
  const pending = [];
  const load = (key, img, foc) => {
    if (running && cache.has(key)) { pending.push([key, img, foc]); return cache.get(key); }
    return upload(key, img, foc);
  };
  const loadDepth = (key, img) => {
    const s = cache.get(key);
    if (!s) return;
    s.dep = texFrom(s.dep === flat ? gl.createTexture() : s.dep, img);
    if (s === A || s === B) request();
  };

  let scale = 1, params = {}, t = 0, mouse = [-1e4, -1e4], raf = 0, A = null, B = null, running = null;
  let epi = new Float32Array(16), reach = 1, seed = 0;
  let view = [0, 0], viewTo = [0, 0], easing = 0;

  const draw = () => {
    raf = 0;
    if (!A) return;
    const p = params, b = B || A;
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, A.tex);
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, b.tex);
    gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, A.dep);
    gl.activeTexture(gl.TEXTURE3); gl.bindTexture(gl.TEXTURE_2D, b.dep);
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(U.res, canvas.width, canvas.height);
    gl.uniform2fv(U.sizeA, A.size); gl.uniform2fv(U.focA, A.foc);
    gl.uniform2fv(U.sizeB, b.size); gl.uniform2fv(U.focB, b.foc);
    gl.uniform2fv(U.mouse, mouse);
    gl.uniform1f(U.cell, Math.max(1, Math.round(p.cell * scale)));
    gl.uniform1f(U.matrix, p.matrix);
    gl.uniform1f(U.levels, p.levels);
    gl.uniform1f(U.spread, p.spread);
    gl.uniform1f(U.sat, p.sat);
    gl.uniform1f(U.con, p.con);
    gl.uniform1f(U.bri, p.bri);
    gl.uniform1f(U.amount, p.on ? p.amount : 0);
    gl.uniform1f(U.lensR, Math.max(1, p.lens * scale));
    gl.uniform1f(U.lensOn, p.lens > 0 ? 1 : 0);
    gl.uniform1f(U.t, t);
    gl.uniform1f(U.seed, seed);
    gl.uniform1f(U.reach, reach);
    gl.uniform1f(U.glow, p.glow ?? .06);
    gl.uniform4fv(U.epi, epi);
    gl.uniform2fv(U.view, view);
    gl.uniform1f(U.parallax, (p.parallax ?? 0) * scale);
    gl.uniform1f(U.relief, p.relief ?? 0);
    gl.uniform1f(U.tilt, p.tilt ?? 0);
    gl.uniform1f(U.grout, p.grout ?? 0);
    gl.uniform1f(U.shadowLen, 7 * scale);
    const pal = PALETTES[p.palette];
    gl.uniform1f(U.palN, pal ? pal.length : 0);
    if (pal) gl.uniform3fv(U.pal, new Float32Array(pal.flatMap(hex).concat(Array(24).fill(0)).slice(0, 24)));
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  };
  // Hidden tabs freeze rAF; draw synchronously so state never goes stale.
  const request = () => { if (document.hidden) draw(); else if (!raf) raf = requestAnimationFrame(draw); };

  // Size from the parent so the canvas attribute never feeds back into layout.
  // Dither cells span several device pixels, so render at dpr / floor(dpr) and let CSS
  // upscale by that whole number (image-rendering: pixelated): the same image, and a
  // quarter of the fragments on a 2x screen.
  const ro = new ResizeObserver(() => {
    const dpr = window.devicePixelRatio || 1;
    scale = dpr / Math.max(1, Math.floor(dpr));
    const r = canvas.parentElement.getBoundingClientRect();
    canvas.width = Math.max(1, Math.round(r.width * scale));
    canvas.height = Math.max(1, Math.round(r.height * scale));
    request();
  });
  ro.observe(canvas.parentElement);

  // Choose where the ink lands, in aspect space (x in 0..a, y in 0..1 from the bottom).
  // Usually two separate sites (a big splash and a smaller, later one) that ripple into each
  // other; otherwise one cluster. Sites avoid the dark corner behind the quote.
  const scatter = () => {
    const a = canvas.width / canvas.height, rnd = Math.random, lerp = (x, y) => x + (y - x) * rnd();
    const site = () => {
      for (let n = 0; n < 20; n++) {
        const x = lerp(.15, .88) * a, y = lerp(.25, .85);
        if (!(x < .5 * a && y < .45)) return [x, y];
      }
      return [.62 * a, .6];
    };
    const blots = [];
    const splash = ([x, y], r, delay, satellites) => {
      blots.push([x, y, r, delay]);
      for (let i = 0; i < satellites; i++) {
        const ang = rnd() * 6.283, d = r * lerp(1.1, 2.2);
        blots.push([x + Math.cos(ang) * d, y + Math.sin(ang) * d, r * lerp(.3, .55), delay + lerp(.01, .04)]);
      }
    };
    const big = site();
    if (rnd() < .6) {
      let small = site();
      for (let n = 0; n < 20 && Math.hypot(small[0] - big[0], small[1] - big[1]) < .35 * Math.max(a, 1); n++) small = site();
      splash(big, lerp(.06, .09), 0, rnd() < .5 ? 2 : 1);
      splash(small, lerp(.035, .055), lerp(.03, .14), 0);
    } else {
      splash(big, lerp(.05, .08), 0, rnd() < .5 ? 3 : 2);
    }
    while (blots.length < 4) blots.push([1e3, 1e3, 0, 0]);
    epi = new Float32Array(blots.slice(0, 4).flat());
    // Scale the wave speed so the corner reached last still settles before t = .93.
    const live = blots.filter(b => b[2] > 0);
    const arrival = r => Math.max(...[[0, 0], [a, 0], [0, 1], [a, 1]].map(([x, y]) =>
      Math.min(...live.map(([px, py, , dl]) => dl + .12 + .74 * Math.pow(Math.min(1, Math.hypot(x - px, y - py) / r), .85)))));
    let lo = .2, hi = 4;
    for (let n = 0; n < 30; n++) { const mid = (lo + hi) / 2; arrival(mid) > .86 ? lo = mid : hi = mid; }
    reach = hi;
    seed = rnd() * 100;
  };

  // The viewpoint follows the pointer with a little lag, and settles back to centre.
  const ease = () => {
    view = view.map((v, i) => v + (viewTo[i] - v) * .12);
    const moving = Math.abs(view[0] - viewTo[0]) + Math.abs(view[1] - viewTo[1]) > .002;
    if (!running) draw();
    easing = moving ? requestAnimationFrame(ease) : 0;
  };

  return {
    load, loadDepth,
    set(p) { params = { ...params, ...p }; request(); },
    show(slot) { A = slot; B = null; t = 0; request(); },
    transition(slot, ms = 1800) {
      if (running) running.cancel();
      B = slot; scatter();
      return new Promise(done => {
        const t0 = performance.now();
        let id = 0;
        const finish = () => {
          cancelAnimationFrame(id); A = slot; B = null; t = 0; running = null;
          pending.splice(0).forEach(args => upload(...args));
          request(); done();
        };
        running = { cancel: finish };
        const step = now => {
          const x = Math.min(1, (now - t0) / ms);
          t = 1 - Math.pow(1 - x, 1.6);   // quick splash, the ripple eases out
          draw();
          if (x < 1) id = requestAnimationFrame(step); else finish();
        };
        id = requestAnimationFrame(step);
      });
    },
    pointer(x, y) {
      mouse = x == null ? [-1e4, -1e4] : [x * scale, canvas.height - y * scale];
      const w = canvas.width / scale, h = canvas.height / scale;
      viewTo = x == null ? [0, 0] : [(x / w - .5) * 2, -(y / h - .5) * 2];
      if (params.parallax > 0 && !easing) easing = requestAnimationFrame(ease);
      if (params.lens > 0) request();
    },
    snapshot() { draw(); return canvas.toDataURL('image/png'); },
  };
}
