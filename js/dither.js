// Ordered (Bayer) dithering of a painting in one WebGL fragment pass.
// Two texture slots (A = current, B = next) so painting changes dissolve
// through the same Bayer matrix instead of a plain crossfade.

const VS = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0., 1.); }`;

const FS = `
precision highp float;
uniform sampler2D texA, texB;
uniform vec2 res, sizeA, sizeB, focA, focB, mouse;
uniform float cell, matrix, levels, spread, sat, con, bri, amount, t, lensR, palN;
uniform vec3 pal[8];

// Recursive Bayer: values in [0,1)
float b2(vec2 a){ a = floor(a); return fract(a.x * .5 + a.y * a.y * .75); }
float b4(vec2 a){ return b2(.5 * a) * .25 + b2(a); }
float b8(vec2 a){ return b4(.5 * a) * .25 + b2(a); }
float bayer(vec2 a){ return matrix > 6. ? b8(a) : matrix > 3. ? b4(a) : b2(a); }

vec2 cover(vec2 uv, vec2 img, vec2 foc){
  float ra = res.x / res.y, ia = img.x / img.y;
  vec2 s = vec2(min(ra / ia, 1.), min(ia / ra, 1.));
  vec2 c = clamp(foc, s * .5, 1. - s * .5);
  return c + (uv - .5) * s;
}
vec3 samplePair(vec2 uv, float useB){
  vec3 a = texture2D(texA, cover(uv, sizeA, focA)).rgb;
  vec3 b = texture2D(texB, cover(uv, sizeB, focB)).rgb;
  return mix(a, b, useB);
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

void main(){
  vec2 fc = gl_FragCoord.xy;
  vec2 cellIx = floor(fc / cell);
  float th = bayer(cellIx);
  // Transition mask: cells whose threshold is under t already show B.
  float useB = step(th, t - .0001) ;
  vec2 uvCell = (cellIx + .5) * cell / res;
  vec3 c = grade(samplePair(uvCell, useB));

  vec3 d;
  if (palN > .5) {
    d = nearest(c + (th - .5) * spread * .5);
  } else {
    float L = levels - 1.;
    d = floor(c * L + th * spread + (1. - spread) * .5) / L;
  }

  vec3 orig = grade(samplePair(fc / res, useB));
  float k = amount;
  if (lensR > 0.) k *= smoothstep(.8, 1., length(fc - mouse) / lensR);
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
  const gl = canvas.getContext('webgl', { antialias: false, preserveDrawingBuffer: true });
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
    const name = gl.getActiveUniform(prog, i).name.replace('[0]', '');
    U[name] = gl.getUniformLocation(prog, gl.getActiveUniform(prog, i).name);
  }
  gl.uniform1i(U.texA, 0); gl.uniform1i(U.texB, 1);

  const slots = [
    { tex: gl.createTexture(), size: [1, 1], foc: [.5, .5] },
    { tex: gl.createTexture(), size: [1, 1], foc: [.5, .5] },
  ];
  const upload = (slot, img, foc) => {
    gl.activeTexture(gl.TEXTURE0 + slot);
    gl.bindTexture(gl.TEXTURE_2D, slots[slot].tex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR],
      [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]])
      gl.texParameteri(gl.TEXTURE_2D, k, v);
    slots[slot].size = [img.naturalWidth, img.naturalHeight];
    slots[slot].foc = [foc[0], 1 - foc[1]];
  };

  let dpr = 1, params = {}, t = 0, mouse = [-1e4, -1e4], raf = 0;

  const draw = () => {
    raf = 0;
    const p = params;
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(U.res, canvas.width, canvas.height);
    gl.uniform2fv(U.sizeA, slots[0].size); gl.uniform2fv(U.focA, slots[0].foc);
    gl.uniform2fv(U.sizeB, slots[1].size); gl.uniform2fv(U.focB, slots[1].foc);
    gl.uniform2fv(U.mouse, mouse);
    gl.uniform1f(U.cell, Math.max(1, Math.round(p.cell * dpr)));
    gl.uniform1f(U.matrix, p.matrix);
    gl.uniform1f(U.levels, p.levels);
    gl.uniform1f(U.spread, p.spread);
    gl.uniform1f(U.sat, p.sat);
    gl.uniform1f(U.con, p.con);
    gl.uniform1f(U.bri, p.bri);
    gl.uniform1f(U.amount, p.on ? p.amount : 0);
    gl.uniform1f(U.lensR, p.lens * dpr);
    gl.uniform1f(U.t, t);
    const pal = PALETTES[p.palette];
    gl.uniform1f(U.palN, pal ? pal.length : 0);
    if (pal) gl.uniform3fv(U.pal, new Float32Array(pal.flatMap(hex).concat(Array(24).fill(0)).slice(0, 24)));
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  };
  const request = () => { if (!raf) raf = requestAnimationFrame(draw); };

  // Size from the parent so the canvas attribute never feeds back into layout.
  const ro = new ResizeObserver(() => {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const r = canvas.parentElement.getBoundingClientRect();
    canvas.width = Math.max(1, Math.round(r.width * dpr));
    canvas.height = Math.max(1, Math.round(r.height * dpr));
    request();
  });
  ro.observe(canvas.parentElement);

  return {
    set(p) { params = { ...params, ...p }; request(); },
    show(img, foc) { upload(0, img, foc); upload(1, img, foc); t = 0; request(); },
    // Dissolve A -> B through the Bayer thresholds.
    transition(img, foc, ms = 1400) {
      upload(1, img, foc);
      return new Promise(done => {
        const t0 = performance.now();
        const step = now => {
          t = Math.min(1, (now - t0) / ms);
          draw();
          if (t < 1) requestAnimationFrame(step);
          else { upload(0, img, foc); t = 0; draw(); done(); }
        };
        requestAnimationFrame(step);
      });
    },
    pointer(x, y) {
      mouse = x == null ? [-1e4, -1e4] : [x * dpr, canvas.height - y * dpr];
      if (params.lens > 0) request();
    },
    snapshot() { draw(); return canvas.toDataURL('image/png'); },
  };
}
