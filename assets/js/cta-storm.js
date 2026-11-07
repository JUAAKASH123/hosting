// cta-storm.js — Storm point-cloud background for the ".cta-section" (VirtuFit purple palette)
import * as THREE from 'three'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js'
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js'
import { GammaCorrectionShader } from 'three/addons/shaders/GammaCorrectionShader.js'
import { CopyShader } from 'three/addons/shaders/CopyShader.js'

const host = document.querySelector('.cta-section')

// ---- Fixed parameters (colors matched to the site: #12002e / #7c4dff / #b39dff) ----
const CONFIG = {
  bgColor: '#12002e',
  flameColor: '#7c4dff',
  flameColor2: '#b39dff',
  flameAmt: 0.2,
  atmoColor: '#b39dff',
  atmoSize: 24,
  coreColor: '#2a0a6e',
  midColor: '#7c4dff',
  rimColor: '#b39dff',
  opacity: 2,
  pointSize: 80,
  brightness: 1.6,
  repelRadius: 1.4,
  repelStrength: 4,
}

function hexToVec3(hex) {
  const n = parseInt(hex.slice(1), 16)
  return new THREE.Vector3(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255)
}
const Lerp = (a, b, t) => a + (b - a) * t
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))

function init() {
  const canvas = document.createElement('canvas')
  canvas.className = 'cta-storm-canvas'
  host.prepend(canvas)

  let W = host.clientWidth, H = host.clientHeight
  const DPR = Math.min(window.devicePixelRatio || 1, 2)

  const renderer = new THREE.WebGL1Renderer({ canvas, antialias: true })
  renderer.setPixelRatio(DPR)
  renderer.setSize(W, H, false)
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.VSMShadowMap

  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x000000)
  scene.fog = new THREE.Fog(0x000000, 0, 15)

  const camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 80)
  camera.position.set(0, 0, 7)
  scene.add(camera)

  const LAYERS = { NONE: 0, TORUS_SCENE: 1, BLOOM_SCENE: 2, ENTIRE_SCENE: 3 }
  camera.layers.enable(LAYERS.TORUS_SCENE)
  camera.layers.enable(LAYERS.BLOOM_SCENE)
  camera.layers.enable(LAYERS.ENTIRE_SCENE)

  // ---------------- Composite pass ----------------
  const blackTex = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1)
  blackTex.needsUpdate = true

  const FinalPass = {
    uniforms: {
      iTime: { value: 0 },
      tDiffuse: { value: null }, torusTexture: { value: null }, bloomTexture: { value: null }, haloTexture: { value: blackTex },
      uBg: { value: hexToVec3(CONFIG.bgColor) },
      uFlameA: { value: hexToVec3(CONFIG.flameColor) },
      uFlameB: { value: hexToVec3(CONFIG.flameColor2) },
      uFlameAmt: { value: CONFIG.flameAmt },
    },
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position, 1.0); }`,
    fragmentShader: `
uniform float iTime; uniform sampler2D tDiffuse; uniform sampler2D bloomTexture; uniform sampler2D torusTexture; uniform sampler2D haloTexture;
uniform vec3 uBg; uniform vec3 uFlameA; uniform vec3 uFlameB; uniform float uFlameAmt;
varying vec2 vUv;
vec3 warp3d(vec3 pos, float t){ float curv=.8,a=1.9,b=0.7; pos*=2.;
  pos.x+=curv*sin(t+a*pos.y)+t*b; pos.y+=curv*cos(t+a*pos.x);
  pos.y+=curv*sin(t+a*pos.z)+t*b; pos.z+=curv*cos(t+a*pos.y);
  pos.z+=curv*sin(t+a*pos.x)+t*b; pos.x+=curv*cos(t+a*pos.z);
  return 0.5+0.5*cos(pos.xyz+vec3(1,2,4)); }
void main(){
  vec2 uv = 2.*vUv - 1.;
  vec3 w = pow(warp3d(vec3(uv.x, sin(uv.y), uv.y), iTime*1.5), vec3(1.5));
  vec3 flame = 1.5*uFlameA*w.x; flame*=w.y; flame += uFlameB*w.z;
  flame *= smoothstep(0.25, 1., abs(uv.y));
  float md = smoothstep(-0.7, 1., -uv.y*uv.x); flame *= md*md;
  vec3 bg = uBg * (1.0 - 0.4 * length(uv));
  vec3 halo = texture2D(haloTexture, vUv).xyz;
  gl_FragColor = vec4(bg + flame*uFlameAmt + texture2D(bloomTexture, vUv).xyz + texture2D(torusTexture, vUv).xyz + texture2D(tDiffuse, vUv).xyz + halo, 1.);
}`,
  }

  // ---------------- Composers ----------------
  const renderScene = new RenderPass(scene, camera)
  const res = () => new THREE.Vector2(W, H)

  const torusComposer = new EffectComposer(renderer)
  torusComposer.renderToScreen = false
  torusComposer.addPass(renderScene)
  torusComposer.addPass(new ShaderPass(GammaCorrectionShader))
  torusComposer.addPass(new UnrealBloomPass(res(), 0.22, 0.2, 0))
  torusComposer.addPass(new ShaderPass(CopyShader))

  const bloomComposer = new EffectComposer(renderer)
  bloomComposer.renderToScreen = false
  bloomComposer.addPass(renderScene)
  bloomComposer.addPass(new UnrealBloomPass(res(), 0.4, 0.55, 0))
  bloomComposer.addPass(new ShaderPass(GammaCorrectionShader))

  const finalComposer = new EffectComposer(renderer)
  finalComposer.addPass(renderScene)
  const finalPass = new ShaderPass(FinalPass)
  finalComposer.addPass(finalPass)
  finalPass.uniforms.bloomTexture.value = bloomComposer.renderTarget1.texture
  finalPass.uniforms.torusTexture.value = torusComposer.renderTarget1.texture

  const composers = [torusComposer, bloomComposer, finalComposer]
  composers.forEach(c => { c.setPixelRatio(DPR); c.setSize(W, H) })

  // ---------------- Storm geometry ----------------
  const count = 50000, radius = 2.5
  const positions = new Float32Array(count * 3)
  const scales = new Float32Array(count), noises = new Float32Array(count)
  const radialPush = new Float32Array(count), mixv = new Float32Array(count)
  for (let i = 0; i < count; i++) {
    const i3 = i * 3
    let u, v, s
    do { u = Math.random() * 2 - 1; v = Math.random() * 2 - 1; s = u * u + v * v } while (s >= 1 || s === 0)
    const factor = 2 * Math.sqrt(1 - s)
    const dx = u * factor, dy = v * factor, dz = 1 - 2 * s
    const rN = Math.pow(Math.random(), 0.4)
    const r = radius * (0.55 + rN * 0.45)
    positions[i3] = dx * r; positions[i3 + 1] = dy * r; positions[i3 + 2] = dz * r
    mixv[i] = rN
    scales[i] = 0.45 + Math.random() * 0.8
    noises[i] = Math.random()
    radialPush[i] = 0.4 + rN * 1.1
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.setAttribute('aScale', new THREE.Float32BufferAttribute(scales, 1))
  geometry.setAttribute('aNoise', new THREE.Float32BufferAttribute(noises, 1))
  geometry.setAttribute('aRadialPush', new THREE.Float32BufferAttribute(radialPush, 1))
  geometry.setAttribute('aMix', new THREE.Float32BufferAttribute(mixv, 1))

  const uniforms = {
    uTime: { value: 0 },
    uSize: { value: CONFIG.pointSize },
    uOpacity: { value: 0 },
    uBlowUp: { value: 0 },
    uCursor: { value: new THREE.Vector3() },
    uRepelRadius: { value: CONFIG.repelRadius },
    uRepelStrength: { value: CONFIG.repelStrength },
    uActivity: { value: 0 },
    uCore: { value: hexToVec3(CONFIG.coreColor) },
    uMid: { value: hexToVec3(CONFIG.midColor) },
    uRim: { value: hexToVec3(CONFIG.rimColor) },
    uBrightness: { value: CONFIG.brightness },
  }

  const material = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, uniforms,
    vertexShader: `
uniform float uTime; uniform float uSize; uniform float uBlowUp;
uniform vec3 uCursor; uniform float uRepelRadius; uniform float uRepelStrength; uniform float uActivity;
uniform vec3 uCore; uniform vec3 uMid; uniform vec3 uRim;
attribute float aScale; attribute float aNoise; attribute float aRadialPush; attribute float aMix;
varying vec3 vColor; varying float vBlowUp;
void main() {
  vec3 pos = position;
  float t = uTime * 1.4 + aNoise * 6.2831;
  float wobble = sin(t) * 0.1 * aRadialPush;
  pos *= 1.0 + wobble;
  float swirlAngle = uTime * 0.05 + aNoise * 6.2831;
  mat2 swirl = mat2(cos(swirlAngle), -sin(swirlAngle), sin(swirlAngle), cos(swirlAngle));
  pos.xz = swirl * pos.xz;
  vec3 outward = normalize(pos + vec3(0.0001));
  float blow = uBlowUp * uBlowUp;
  pos += outward * blow * (10.0 + aNoise * 18.0) * aRadialPush;
  vec4 modelPosition = modelMatrix * vec4(pos, 1.0);
  vec3 toParticle = modelPosition.xyz - uCursor;
  float dist = length(toParticle);
  float falloff = smoothstep(uRepelRadius, 0.0, dist);
  modelPosition.xyz += normalize(toParticle + vec3(0.0001)) * falloff * uRepelStrength * uActivity;
  vec4 viewPosition = viewMatrix * modelPosition;
  gl_Position = projectionMatrix * viewPosition;
  gl_PointSize = uSize * aScale;
  gl_PointSize *= (1.0 / -viewPosition.z);
  float t1 = smoothstep(0.25, 0.85, aMix);
  vec3 mix1 = mix(uCore, uMid, t1);
  float t2 = clamp((aMix - 0.7) * 3.0, 0.0, 1.0);
  vColor = mix(mix1, uRim, t2);
  vBlowUp = uBlowUp;
}`,
    fragmentShader: `
uniform float uOpacity; uniform float uBrightness;
varying vec3 vColor; varying float vBlowUp;
void main() {
  vec2 uv = gl_PointCoord - 0.5;
  float d = length(uv);
  if (d > 0.5) discard;
  float strength = pow(1.0 - d * 2.0, 4.5);
  vec3 color = mix(vec3(0.0), vColor, strength);
  float blowFade = 1.0 - smoothstep(0.15, 1.0, vBlowUp);
  gl_FragColor = vec4(color * uBrightness, strength * uOpacity * blowFade);
}`,
  })

  const points = new THREE.Points(geometry, material)
  points.layers.enable(LAYERS.ENTIRE_SCENE)
  const group = new THREE.Group()
  group.add(points)
  scene.add(group)

  // ---------------- Atmosphere motes ----------------
  const N = 300
  const aPos = new Float32Array(N * 3), aSize = new Float32Array(N), aSeed = new Float32Array(N)
  for (let i = 0; i < N; i++) {
    aPos[i * 3] = 2 * Math.random() - 1; aPos[i * 3 + 1] = 2 * Math.random() - 1; aPos[i * 3 + 2] = 2 * Math.random() - 1
    aSize[i] = CONFIG.atmoSize * (0.4 + Math.random()); aSeed[i] = Math.random()
  }
  const atmoGeo = new THREE.BufferGeometry()
  atmoGeo.setAttribute('position', new THREE.Float32BufferAttribute(aPos, 3))
  atmoGeo.setAttribute('size', new THREE.Float32BufferAttribute(aSize, 1))
  atmoGeo.setAttribute('seed', new THREE.Float32BufferAttribute(aSeed, 1))
  const atmoMat = new THREE.ShaderMaterial({
    transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false,
    uniforms: {
      uTime: { value: 0 },
      uColor: { value: hexToVec3(CONFIG.atmoColor) },
      uRes: { value: new THREE.Vector2(W * DPR, H * DPR) },
    },
    vertexShader: `
attribute float size; attribute float seed; uniform float uTime; uniform vec2 uRes;
varying float vA;
vec3 warp(vec3 p, float t){ float c=0.9,a=1.9,b=0.02,s=0.05; p*=2.;
  p.x+=c*sin(s*t+a*p.y)+t*b; p.y+=c*cos(s*t+a*p.x); p.y+=c*sin(s*t+a*p.z)+t*b;
  p.z+=c*cos(s*t+a*p.y); p.z+=c*sin(s*t+a*p.x)+t*b; p.x+=c*cos(s*t+a*p.z);
  return cos(p+vec3(1,2,4)); }
void main(){
  vec3 v = position*4.0 + warp(position, uTime)*1.2;
  vec4 mv = modelViewMatrix * vec4(v, 1.0);
  float r = length(v); float farF = 1.0 - smoothstep(5.0, 6.5, r); float nearF = smoothstep(0.0, 0.5, -mv.z);
  vA = farF * nearF;
  gl_PointSize = size * uRes.y / 900.0 / -mv.z; gl_PointSize = max(gl_PointSize, 1.0);
  gl_Position = projectionMatrix * mv;
}`,
    fragmentShader: `
uniform vec3 uColor; varying float vA;
void main(){ vec2 p = gl_PointCoord - 0.5; float l = length(p); if (l > 0.5) discard;
  float tex = smoothstep(0.5, 0.0, l); gl_FragColor = vec4(uColor * tex, tex * vA * 0.6); }`,
  })
  const atmo = new THREE.Points(atmoGeo, atmoMat)
  atmo.frustumCulled = false
  atmo.layers.enable(LAYERS.ENTIRE_SCENE)
  atmo.onBeforeRender = () => {
    const t = performance.now() / 1000
    atmoMat.uniforms.uTime.value = t * 1.0 * 8.0
    atmo.position.copy(camera.position)
    finalPass.uniforms.iTime.value = t
  }
  scene.add(atmo)

  // ---------------- Pointer (section-local) ----------------
  const POINTER = { ndc: new THREE.Vector2(0, 0), world: new THREE.Vector3(), activity: 0, active: false, lastMove: performance.now() }
  host.addEventListener('mousemove', e => {
    const r = host.getBoundingClientRect()
    POINTER.ndc.x = ((e.clientX - r.left) / r.width) * 2 - 1
    POINTER.ndc.y = -(((e.clientY - r.top) / r.height) * 2 - 1)
    POINTER.active = true; POINTER.lastMove = performance.now()
  }, { passive: true })
  host.addEventListener('mouseleave', () => { POINTER.active = false }, { passive: true })

  const _ndc = new THREE.Vector3(), _dir = new THREE.Vector3(), _target = new THREE.Vector3()
  function updatePointer() {
    _target.set(0, 0, 0)
    if (POINTER.active) {
      _ndc.set(POINTER.ndc.x, POINTER.ndc.y, 0.5).unproject(camera)
      _dir.copy(_ndc).sub(camera.position).normalize()
      const denom = _dir.z
      if (Math.abs(denom) > 1e-4) {
        const t = -camera.position.z / denom
        if (t > 0 && Number.isFinite(t)) _target.copy(camera.position).addScaledVector(_dir, t)
      }
    }
    POINTER.world.lerp(_target, 0.12)
    const idle = (performance.now() - POINTER.lastMove) / 1000
    const want = (POINTER.active && idle < 3) ? 1 : 0
    POINTER.activity += (want - POINTER.activity) * 0.06
  }

  // ---------------- Scroll progress of the section through the viewport ----------------
  let scrollTarget = 0, scrollSmooth = 0, scrollCurrent = 0
  const mouseSmooth = { x: 0, y: 0 }
  function updateScroll() {
    const r = host.getBoundingClientRect()
    const vh = window.innerHeight
    scrollTarget = clamp((vh - r.top) / (vh + r.height), 0, 1)
  }
  window.addEventListener('scroll', updateScroll, { passive: true })
  updateScroll()

  // ---------------- Resize ----------------
  function resize() {
    W = host.clientWidth; H = host.clientHeight
    if (!W || !H) return
    renderer.setPixelRatio(DPR); renderer.setSize(W, H, false)
    camera.aspect = W / H; camera.updateProjectionMatrix()
    composers.forEach(c => { c.setPixelRatio(DPR); c.setSize(W, H) })
    atmoMat.uniforms.uRes.value.set(W * DPR, H * DPR)
    updateScroll()
  }
  new ResizeObserver(resize).observe(host)

  // ---------------- Render loop (only while the section is on screen) ----------------
  let visible = true, last = performance.now() / 1000
  const appearStart = performance.now()
  new IntersectionObserver(es => { visible = es[0].isIntersecting }).observe(host)

  function render() {
    requestAnimationFrame(render)
    if (!visible) return
    scrollSmooth = Lerp(scrollSmooth, scrollTarget, 0.10)
    scrollCurrent = Lerp(scrollCurrent, scrollSmooth, 0.06)
    mouseSmooth.x = Lerp(mouseSmooth.x, POINTER.ndc.x, 0.06)
    mouseSmooth.y = Lerp(mouseSmooth.y, POINTER.ndc.y, 0.06)
    updatePointer()

    const t = performance.now() / 1000
    const dt = Math.min(0.05, t - last); last = t
    const scroll = scrollCurrent
    uniforms.uTime.value = t
    camera.position.set(mouseSmooth.x * 0.7, mouseSmooth.y * 0.7, 7 - scroll * 3)
    camera.lookAt(0, 0, 0)
    group.scale.setScalar(1 + scroll * 0.5)
    const fade = clamp((performance.now() - appearStart - 300) / 1400, 0, 1)
    uniforms.uOpacity.value = fade * CONFIG.opacity
    uniforms.uBlowUp.value = 0
    uniforms.uCursor.value.copy(POINTER.world)
    uniforms.uActivity.value = POINTER.activity
    group.rotation.y += dt * (0.03 + scroll * 0.6)
    group.rotation.x += dt * 0.03 * 0.33

    camera.layers.set(LAYERS.TORUS_SCENE); torusComposer.render()
    camera.layers.set(LAYERS.BLOOM_SCENE); bloomComposer.render()
    camera.layers.set(LAYERS.ENTIRE_SCENE); finalComposer.render()
  }
  render()
}

if (host) {
  try { init() } catch (err) { console.warn('Storm background disabled:', err) }
}