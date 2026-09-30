// Ordered (Bayer) dithering of a painting in one WebGL fragment pass.
// Every painting is uploaded once to its own texture. A transition ("ink blot to ripple")
// only decides, per dither cell, when that cell swaps from painting A to B: a few ink
// blots near the centre flip first, then a ripple spreads outward from them. Cells the
// ripple hasn't reached are untouched, and the Bayer pattern never moves.

const VS = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`;

const FS = `
precision highp float;
uniform sampler2D texA, texB;
uniform vec2 res, sizeA, sizeB, focA, focB, mouse;
uniform float cell, matrix, levels, spread, sat, con, bri, amount, lensR, palN;
uniform float t, seed, reach, glow;        // transition progress, per-transition seed, ripple extent, crest brightness
uniform vec3 epi[4];                       // ink blots: xy in aspect space, z = radius
uniform float lensOn;
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
// Signed distance to the nearest ink blot (negative inside). Blot edges are lobed by
// direction noise so they read as splashes, not circles.
float blotField(vec2 p){
  float f = 1e9;
  for (int i = 0; i < 4; i++){
    vec2 d = p - epi[i].xy;
    float lobes = vnoise(normalize(d + 1e-5) * 2.2 + float(i) * 5.3 + seed);
    float grain = vnoise(p * 18. + seed) * .25;
    f = min(f, length(d) - epi[i].z * (.55 + .8 * lobes + grain));
  }
  return f;
}
// x: how far (0..1) this cell has turned into B; y: ripple-crest brightness.
vec2 swap(vec2 uv, vec2 ix){
  if (t <= 0.) return vec2(0.);
  vec2 p = uv * vec2(res.x / res.y, 1.);
  float f = blotField(p);
  float ts;
  if (f < 0.) ts = .12 * clamp(1. + f / .07, 0., 1.);                          // the blot splashes in fast
  else ts = .12 + .74 * pow(clamp(f / reach, 0., 1.), .85)                     // then the ripple spreads
          + (vnoise(p * 6. + seed) - .5) * .07 + (hash(ix + seed) - .5) * .035; // ragged, per-pixel front
  if (f < .1 && hash(floor(ix * .5) + seed * 3.) < .06) ts = min(ts, .08);    // spatter near the blots
  float w = .07;
  float k = smoothstep(ts, ts + w, t);
  float crest = f > 0. ? exp(-pow((t - ts - w * .5) / .035, 2.)) : 0.;
  return vec2(k, crest);
}
vec3 scene(vec2 uv, float k){
  vec3 a = texture2D(texA, cover(uv, sizeA, focA)).rgb;
  return k > 0. ? mix(a, texture2D(texB, cover(uv, sizeB, focB)).rgb, k) : a;
}

void main(){
  vec2 fc = gl_FragCoord.xy;
  vec2 ix = floor(fc / cell);
  float th = bayer(ix);
  vec2 uvc = (ix + .5) * cell / res;
  vec2 sw = swap(uvc, ix);

  vec3 col = grade(scene(uvc, sw.x)) + sw.y * glow;

  vec3 d;
  if (palN > .5) d = nearest(col + (th - .5) * spread * .5);
  else { float L = levels - 1.; d = floor(col * L + th * spread + (1. - spread) * .5) / L; }

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
  gl.uniform1i(U.texA, 0); gl.uniform1i(U.texB, 1);

  const cache = new Map();   // key -> { tex, size, foc }
  // Upload (or re-upload a sharper copy of) an image into the key's texture.
  const upload = (key, img, foc) => {
    let s = cache.get(key);
    if (!s) { s = { tex: gl.createTexture(), foc: [foc[0], 1 - foc[1]] }; cache.set(key, s); }
    gl.bindTexture(gl.TEXTURE_2D, s.tex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR],
      [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]])
      gl.texParameteri(gl.TEXTURE_2D, k, v);
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

  let scale = 1, params = {}, t = 0, mouse = [-1e4, -1e4], raf = 0, A = null, B = null, running = null;
  let epi = new Float32Array(12), reach = 1, seed = 0;

  const draw = () => {
    raf = 0;
    if (!A) return;
    const p = params, b = B || A;
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, A.tex);
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, b.tex);
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
    gl.uniform3fv(U.epi, epi);
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

  // Pick 3-4 ink blots clustered near the middle of the frame, in aspect space (x in 0..aspect).
  const scatter = () => {
    const a = canvas.width / canvas.height, rnd = Math.random;
    const cx = a * (.5 + (rnd() - .5) * .3), cy = .5 + (rnd() - .5) * .25;
    const n = 3 + (rnd() < .5 ? 1 : 0), pts = [];
    for (let i = 0; i < 4; i++) {
      const ang = rnd() * 6.283, dist = i === 0 ? 0 : .05 + rnd() * .13;
      pts.push(i < n ? [cx + Math.cos(ang) * dist, cy + Math.sin(ang) * dist, .035 + rnd() * .045] : [1e3, 1e3, 0]);
    }
    epi = new Float32Array(pts.flat());
    // The ripple has to reach the corner farthest from its nearest blot.
    reach = Math.max(...[[0, 0], [a, 0], [0, 1], [a, 1]].map(([x, y]) =>
      Math.min(...pts.slice(0, n).map(([px, py]) => Math.hypot(x - px, y - py))))) + .05;
    seed = rnd() * 100;
  };

  return {
    load,
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
      if (params.lens > 0) request();
    },
    snapshot() { draw(); return canvas.toDataURL('image/png'); },
  };
}
