/* scene3d.js — 3D-модель Земли и спутниковой сети на Three.js (r128, UMD-глобал THREE).
   Координаты: данные Earth-fixed XYZ (Z — северный полюс) отображаются в three.js
   как (x, z, y), чтобы северный полюс был по +Y. Вся сцена (Земля + объекты)
   вращается вокруг оси Y на угол −(angle0 + OMEGA·t) — планета «крутится»
   (относительно звёздного фона), спутники остаются над теми же пунктами. */
"use strict";

const EARTH_R = 6371.0;
const EARTH_OMEGA = 2 * Math.PI / 86164.09054; // рад/с, как в geometry.py

function dataToThree(x, y, z) { return [x, z, y]; }

class Scene3D {
  constructor(container) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, 1, 100, 500000);

    // камера-орбита (свой контроллер: drag — вращение, колесо — зум)
    this.azimuth = 0.7;
    this.polar = 1.15;
    this.radius = 26000;
    this._applyCamera();

    // свет
    this.scene.add(new THREE.AmbientLight(0x8899bb, 0.55));
    const sun = new THREE.DirectionalLight(0xffffff, 0.95);
    sun.position.set(22000, 32000, 16000);
    this.scene.add(sun);

    this._buildStars();

    // мировая группа (вращается с t)
    this.world = new THREE.Group();
    this.scene.add(this.world);
    this._buildEarth();

    // динамические объекты
    this.satGroup = new THREE.Group();
    this.siteGroup = new THREE.Group();
    this.linkGroup = new THREE.Group();
    this.routeGroup = new THREE.Group();
    this.world.add(this.satGroup, this.siteGroup, this.linkGroup, this.routeGroup);

    this.satMeshes = new Map();   // id -> mesh
    this.siteMeshes = new Map();  // id -> mesh
    this.satellites = [];
    this.groundSites = [];
    this.tS = 0;
    this.earthAngle0 = 0;
    this.hovered = null;
    this.selected = null;
    this.onHover = null;
    this.onSelect = null;

    // подпись для наведённого/выбранного спутника (внутри вращающейся группы)
    this.hoverLabel = this._makeLabelSprite("", "#eaf3fb");
    this.hoverLabel.visible = false;
    this.world.add(this.hoverLabel);

    this._raycaster = new THREE.Raycaster();
    this._mouse = new THREE.Vector2();
    this._mouseInside = false;
    this._bindEvents();
    this._resize();
    this._observer = new ResizeObserver(() => this._resize());
    this._observer.observe(container);
    this._loop();
  }

  /* ---------- статика сцены ---------- */
  _buildStars() {
    const N = 1400, pos = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) {
      // равномерное случайное направление на сфере без Vector3.randomDirection()
      // (метод недоступен в подключённой сборке three.js) — cos(theta) равномерно
      // на [-1,1], phi равномерно на [0, 2π] даёт равномерное распределение по сфере.
      const u = Math.random() * 2 - 1;
      const phi = Math.random() * 2 * Math.PI;
      const s = Math.sqrt(1 - u * u);
      const dx = s * Math.cos(phi), dy = s * Math.sin(phi), dz = u;
      const r = 140000 + Math.random() * 60000;
      pos.set([dx * r, dy * r, dz * r], i * 3);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    this.scene.add(new THREE.Points(g, new THREE.PointsMaterial({
      color: 0xaac4dd, size: 130, sizeAttenuation: true, transparent: true, opacity: 0.75,
    })));
  }

  _buildEarth() {
    const R = EARTH_R;
    const sphere = new THREE.Mesh(
      new THREE.SphereGeometry(R, 64, 48),
      new THREE.MeshPhongMaterial({ color: 0x14293f, emissive: 0x0a1626, shininess: 6, specular: 0x1c3346 })
    );
    this.world.add(sphere);

    // гратикула (сетка lat/lon каждые 30°)
    const pts = [];
    const seg = (a, b) => { pts.push(a[0], a[1], a[2], b[0], b[1], b[2]); };
    const onSphere = (latDeg, lonDeg) => {
      const la = latDeg * Math.PI / 180, lo = lonDeg * Math.PI / 180;
      const r = R * 1.002;
      return [r * Math.cos(la) * Math.cos(lo), r * Math.sin(la), r * Math.cos(la) * Math.sin(lo)];
    };
    for (let lat = -60; lat <= 60; lat += 30) {
      let prev = onSphere(lat, -180);
      for (let lon = -174; lon <= 180; lon += 6) {
        const cur = onSphere(lat, lon);
        seg(prev, cur); prev = cur;
      }
    }
    for (let lon = -180; lon < 180; lon += 30) {
      let prev = onSphere(-90, lon);
      for (let lat = -84; lat <= 90; lat += 6) {
        const cur = onSphere(lat, lon);
        seg(prev, cur); prev = cur;
      }
    }
    const gg = new THREE.BufferGeometry();
    gg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(pts), 3));
    this.world.add(new THREE.LineSegments(gg, new THREE.LineBasicMaterial({
      color: 0x3d6a8f, transparent: true, opacity: 0.35,
    })));

    // подсветка северных широт (пункты северные): полусфера lat > 55°
    const capPolar = (90 - 55) * Math.PI / 180;
    const cap = new THREE.Mesh(
      new THREE.SphereGeometry(R * 1.006, 48, 16, 0, Math.PI * 2, 0, capPolar),
      new THREE.MeshBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.07, side: THREE.DoubleSide, depthWrite: false })
    );
    this.world.add(cap);

    // ореол атмосферы
    const atmo = new THREE.Mesh(
      new THREE.SphereGeometry(R * 1.045, 48, 32),
      new THREE.MeshBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.05, side: THREE.BackSide })
    );
    this.world.add(atmo);
  }

  /* ---------- данные ---------- */
  setSnapshot({ satellites, edges, groundSites, routePath, tS, earthAngle0Deg }) {
    if (earthAngle0Deg !== undefined) this.earthAngle0 = earthAngle0Deg * Math.PI / 180;
    if (tS !== undefined) this.tS = tS;
    this.satellites = satellites || [];
    this._rebuildSats();
    if (groundSites && groundSites !== this.groundSites) {
      this.groundSites = groundSites;
      this._rebuildSites();
    }
    this._rebuildLinks(edges || []);
    this.setRoute(routePath || null);
    this._updateHoverLabel();
  }

  setRoute(pathIds) {
    this._clearGroup(this.routeGroup);
    if (!pathIds || pathIds.length < 2) return;
    const pos = pathIds.map(id => this._nodePos(id));
    if (pos.some(p => !p)) return;
    const linePts = [];
    for (let i = 0; i + 1 < pos.length; i++) linePts.push(...pos[i], ...pos[i + 1]);
    const lg = new THREE.BufferGeometry();
    lg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(linePts), 3));
    this.routeGroup.add(new THREE.LineSegments(lg, new THREE.LineBasicMaterial({
      color: 0x34d399, transparent: true, opacity: 0.95, depthTest: true,
    })));
    const nodeMat = new THREE.MeshBasicMaterial({ color: 0x34d399 });
    const glowMat = new THREE.MeshBasicMaterial({ color: 0x34d399, transparent: true, opacity: 0.25 });
    for (const p of pos) {
      const n = new THREE.Mesh(new THREE.SphereGeometry(120, 10, 10), nodeMat);
      n.position.set(p[0], p[1], p[2]);
      const glow = new THREE.Mesh(new THREE.SphereGeometry(260, 10, 10), glowMat);
      glow.position.copy(n.position);
      this.routeGroup.add(n, glow);
    }
  }

  setHovered(id) {
    if (this.hovered === id) return;
    const prev = this.satMeshes.get(this.hovered);
    if (prev) prev.scale.setScalar(1);
    this.hovered = id;
    const cur = this.satMeshes.get(id);
    if (cur) cur.scale.setScalar(1.7);
    this._updateHoverLabel();
  }

  setSelected(id) {
    this.selected = id;
    this._updateHoverLabel();
  }

  resetView() {
    this.azimuth = 0.7;
    this.polar = 1.15;
    this.radius = 26000;
    this._applyCamera();
  }

  /* ---------- внутренние построители ---------- */
  _clearGroup(g) {
    while (g.children.length) {
      const c = g.children.pop();
      if (c.geometry) c.geometry.dispose();
      if (c.material) c.material.dispose();
      g.remove(c);
    }
  }

  _rebuildSats() {
    this._clearGroup(this.satGroup);
    this.satMeshes.clear();
    const geo = new THREE.SphereGeometry(72, 10, 10);
    const glowGeo = new THREE.SphereGeometry(150, 10, 10);
    for (const s of this.satellites) {
      const [x, y, z] = dataToThree(s.x_km, s.y_km, s.z_km);
      const failed = s.status === "failed";
      const color = failed ? 0xf87171 : (s.active ? 0x22d3ee : 0x4b5563);
      const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color }));
      mesh.position.set(x, y, z);
      mesh.userData = { id: s.id, kind: "sat", ref: s };
      if (s.active || failed) {
        const glow = new THREE.Mesh(glowGeo, new THREE.MeshBasicMaterial({
          color, transparent: true, opacity: failed ? 0.3 : 0.22,
        }));
        mesh.add(glow); // глоу двигается вместе с точкой
      }
      this.satGroup.add(mesh);
      this.satMeshes.set(s.id, mesh);
    }
  }

  _rebuildSites() {
    this._clearGroup(this.siteGroup);
    this.siteMeshes.clear();
    for (const g of this.groundSites) {
      const la = g.lat_deg * Math.PI / 180, lo = g.lon_deg * Math.PI / 180;
      const r = EARTH_R * 1.004;
      const pos = [r * Math.cos(la) * Math.cos(lo), r * Math.sin(la), r * Math.cos(la) * Math.sin(lo)];
      const isGw = g.role === "gateway";
      const color = isGw ? 0x34d399 : 0xfbbf24;
      const mesh = new THREE.Mesh(
        isGw ? new THREE.OctahedronGeometry(240) : new THREE.BoxGeometry(260, 260, 260),
        new THREE.MeshBasicMaterial({ color })
      );
      mesh.position.set(...pos);
      // ориентируем маркер по нормали поверхности
      mesh.lookAt(pos[0] * 2, pos[1] * 2, pos[2] * 2);
      mesh.userData = { id: g.id, kind: "ground", ref: g };
      this.siteGroup.add(mesh);
      this.siteMeshes.set(g.id, mesh);

      const label = this._makeLabelSprite(g.id, isGw ? "#34d399" : "#fbbf24");
      const n = new THREE.Vector3(...pos).normalize();
      label.position.set(pos[0] + n.x * 620, pos[1] + n.y * 620, pos[2] + n.z * 620);
      this.siteGroup.add(label);
    }
  }

  _rebuildLinks(edges) {
    this._clearGroup(this.linkGroup);
    const satIds = new Set(this.satellites.map(s => s.id));
    const isl = [], ground = [];
    for (const e of edges) {
      const pa = this._nodePos(e[0]), pb = this._nodePos(e[1]);
      if (!pa || !pb) continue;
      (satIds.has(e[0]) && satIds.has(e[1]) ? isl : ground).push(...pa, ...pb);
    }
    const mk = (pts, color, opacity) => {
      if (!pts.length) return;
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(pts), 3));
      this.linkGroup.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({
        color, transparent: true, opacity, depthWrite: false,
      })));
    };
    mk(isl, 0x22d3ee, 0.18);
    mk(ground, 0xfbbf24, 0.42);
  }

  _nodePos(id) {
    const m = this.satMeshes.get(id);
    if (m) return [m.position.x, m.position.y, m.position.z];
    const s = this.siteMeshes.get(id);
    if (s) return [s.position.x, s.position.y, s.position.z];
    return null;
  }

  _makeLabelSprite(text, color) {
    const cv = document.createElement("canvas");
    cv.width = 256; cv.height = 64;
    const ctx = cv.getContext("2d");
    ctx.font = "bold 30px Consolas, monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.shadowColor = "rgba(0,0,0,0.9)";
    ctx.shadowBlur = 6;
    ctx.fillStyle = color;
    ctx.fillText(text, 128, 32);
    const tex = new THREE.CanvasTexture(cv);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: true, transparent: true }));
    sp.scale.set(1500, 375, 1);
    return sp;
  }

  _updateHoverLabel() {
    const id = this.hovered || this.selected;
    const m = this.satMeshes.get(id);
    if (!m) { this.hoverLabel.visible = false; return; }
    if (this.hoverLabel.userData.text !== id) {
      this.world.remove(this.hoverLabel);
      this.hoverLabel.material.map.dispose();
      this.hoverLabel.material.dispose();
      this.hoverLabel = this._makeLabelSprite(id, "#eaf3fb");
      this.hoverLabel.userData.text = id;
      this.world.add(this.hoverLabel);
    }
    const off = m.position.clone().normalize().multiplyScalar(340);
    this.hoverLabel.position.copy(m.position).add(off);
    this.hoverLabel.visible = true;
  }

  /* ---------- камера и события ---------- */
  _applyCamera() {
    const sp = Math.sin(this.polar), cp = Math.cos(this.polar);
    this.camera.position.set(
      this.radius * sp * Math.sin(this.azimuth),
      this.radius * cp,
      this.radius * sp * Math.cos(this.azimuth)
    );
    this.camera.lookAt(0, 0, 0);
  }

  _bindEvents() {
    const el = this.renderer.domElement;
    let drag = null;
    el.addEventListener("pointerdown", e => {
      drag = { x: e.clientX, y: e.clientY, moved: false };
      el.setPointerCapture(e.pointerId);
    });
    el.addEventListener("pointermove", e => {
      const rect = el.getBoundingClientRect();
      this._mouse.set(((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1);
      this._mouseInside = true;
      if (drag) {
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
        drag.x = e.clientX; drag.y = e.clientY;
        this.azimuth -= dx * 0.005;
        this.polar = Math.max(0.08, Math.min(Math.PI - 0.08, this.polar - dy * 0.005));
        this._applyCamera();
      }
    });
    el.addEventListener("pointerup", e => {
      if (drag && !drag.moved) this._pick(true);
      drag = null;
    });
    el.addEventListener("pointerleave", () => {
      this._mouseInside = false;
      if (this.onHover) this.onHover(null);
    });
    el.addEventListener("wheel", e => {
      e.preventDefault();
      this.radius = Math.max(9000, Math.min(80000, this.radius * (e.deltaY > 0 ? 1.12 : 1 / 1.12)));
      this._applyCamera();
    }, { passive: false });
  }

  _pick(isClick) {
    if (!this._mouseInside) return;
    this._raycaster.setFromCamera(this._mouse, this.camera);
    const hits = this._raycaster.intersectObjects(
      [...this.satMeshes.values(), ...this.siteMeshes.values()], false);
    const hit = hits.length ? hits[0].object.userData : null;
    if (isClick) {
      this.selected = hit ? hit.id : null;
      this._updateHoverLabel();
      if (this.onSelect) this.onSelect(hit);
    } else if (hit ? hit.id !== this.hovered : this.hovered !== null) {
      this.setHovered(hit ? hit.id : null);
      if (this.onHover) this.onHover(hit);
    }
  }

  _resize() {
    const w = Math.max(200, this.container.clientWidth);
    const h = Math.max(200, this.container.clientHeight);
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  _loop() {
    requestAnimationFrame(() => this._loop());
    // вращение планеты (вместе с группировкой в Earth-fixed) против звёзд
    this.world.rotation.y = -(this.earthAngle0 + EARTH_OMEGA * this.tS);
    this._pick(false);
    this.renderer.render(this.scene, this.camera);
  }
}

window.Scene3D = Scene3D;