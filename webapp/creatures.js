// Генератор істот. Кожна істота виростає з seed (її «ДНК») — унікальна і непередбачувана.
// Символи сітки: o контур, b тіло, d тінь, h відблиск, l черево, p візерунок, a акцент,
// w білок ока, k зіниця, r румʼянець, x аксесуар темний, y аксесуар яскравий, s іскра

const CW = 30, CH = 26, GROUND = CH - 2;
const RARITY_COLOR = { common: "#9BB58A", rare: "#5EA8FF", epic: "#B57BFF", legendary: "#FFC23D" };
const RARITY_NAME = { common: "звичайна", rare: "рідкісна", epic: "епічна", legendary: "легендарна" };

function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function makeCreature(seed, rarity = "common") {
  const R = mulberry32(seed);
  const ri = (a, b) => a + Math.floor(R() * (b - a + 1));
  const pick = (arr) => arr[Math.floor(R() * arr.length)];
  const chance = (p) => R() < p;
  const tier = { common: 0, rare: 1, epic: 2, legendary: 3 }[rarity] ?? 0;

  const g = Array.from({ length: CH }, () => Array(CW).fill("."));
  const inb = (x, y) => x >= 0 && x < CW && y >= 0 && y < CH;
  const get = (x, y) => (inb(x, y) ? g[y][x] : ".");
  const set = (x, y, c) => { x = Math.round(x); y = Math.round(y); if (inb(x, y)) g[y][x] = c; };
  const ell = (cx, cy, rx, ry, c, only) => {
    for (let y = Math.floor(cy - ry - 1); y <= Math.ceil(cy + ry + 1); y++)
      for (let x = Math.floor(cx - rx - 1); x <= Math.ceil(cx + rx + 1); x++) {
        const dx = (x - cx) / (rx + 0.4), dy = (y - cy) / (ry + 0.4);
        if (dx * dx + dy * dy <= 1 && (!only || only.includes(get(x, y)))) set(x, y, c);
      }
  };
  const limb = (x1, y1, x2, y2, r1, r2, c, only) => {
    const n = Math.ceil(Math.hypot(x2 - x1, y2 - y1) * 2) + 1;
    for (let i = 0; i <= n; i++) {
      const t = i / n, r = r1 + (r2 - r1) * t;
      ell(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, r, r, c, only);
    }
  };
  const tri = (p1, p2, p3, c, only) => {
    const xs = [p1[0], p2[0], p3[0]], ys = [p1[1], p2[1], p3[1]];
    const s = (a, b, p) => (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1]);
    for (let y = Math.floor(Math.min(...ys)); y <= Math.ceil(Math.max(...ys)); y++)
      for (let x = Math.floor(Math.min(...xs)); x <= Math.ceil(Math.max(...xs)); x++) {
        const p = [x, y], d1 = s(p, p1, p2), d2 = s(p, p2, p3), d3 = s(p, p3, p1);
        const neg = d1 < 0 || d2 < 0 || d3 < 0, pos = d1 > 0 || d2 > 0 || d3 > 0;
        if (!(neg && pos) && (!only || only.includes(get(x, y)))) set(x, y, c);
      }
  };

  // ---------- тіло
  const kind = pick(["biped", "biped", "quad", "longneck", "blob", "blob", "flyer", "serpent"]);
  let bx, by, brx, bry, hx, hy, hrx, hry, tailEnd = null;
  const legs = [];

  if (kind === "biped" || kind === "quad" || kind === "longneck") {
    const quad = kind !== "biped";
    brx = quad ? ri(6, 8) : ri(4, 6);
    bry = quad ? ri(3, 4) : ri(3, 5);
    const legH = ri(2, quad ? 4 : 5);
    bx = quad ? ri(12, 14) : ri(11, 13);
    by = GROUND - legH - bry + 1;
    ell(bx, by, brx, bry, "b");
    const lx = quad ? [bx - brx + 2, bx - brx + 4, bx + brx - 4, bx + brx - 2] : [bx - 1, bx + 2];
    for (const x of lx) { limb(x, by + bry - 1, x, GROUND - 1, 1.1, 0.9, "b"); set(x + 1, GROUND, "b"); set(x, GROUND, "b"); legs.push(x); }
    hrx = ri(2, 4); hry = ri(2, 3);
    if (kind === "longneck") { hx = bx + brx + ri(0, 2); hy = by - bry - ri(6, 9); }
    else if (quad) { hx = bx + brx + ri(1, 3); hy = by - ri(0, 3); }
    else { hx = bx + brx + ri(0, 2); hy = by - bry - ri(1, 3); }
    limb(bx + brx - 2, by - bry + 2, hx - 1, hy + 1, kind === "longneck" ? 1.6 : 2, 1.2, "b");
    ell(hx, hy, hrx, hry, "b");
    ell(hx + hrx, hy + 1, ri(1, 2), 1, "b");
    const tx = bx - brx - ri(4, 8), ty = by + ri(-4, 3);
    limb(bx - brx + 2, by, tx, ty, 2, 0, "b");
    tailEnd = [tx, ty];
    if (!quad && chance(0.8)) limb(bx + brx - 1, by + 1, bx + brx + 2, by + 3, 0.6, 0.4, "b");
  } else if (kind === "blob") {
    brx = ri(6, 9); bry = ri(5, 7);
    bx = 14; by = GROUND - bry - 1;
    ell(bx, by, brx, bry, "b");
    hx = bx + ri(0, 3); hy = by - ri(1, 3); hrx = brx - 2; hry = bry - 2;
    ell(bx - 3, GROUND, 1.5, 1, "b"); ell(bx + 3, GROUND, 1.5, 1, "b");
    if (chance(0.5)) { // вушка
      tri([bx - 4, by - bry + 1], [bx - 6, by - bry - 3], [bx - 1, by - bry], "b");
      tri([bx + 4, by - bry + 1], [bx + 6, by - bry - 3], [bx + 1, by - bry], "b");
    }
    if (chance(0.4)) { tailEnd = [bx - brx - 3, by + 2]; limb(bx - brx + 1, by + 2, ...tailEnd, 1.4, 0, "b"); }
  } else if (kind === "flyer") {
    bx = 14; by = 14; brx = 3; bry = 4;
    const wy = ri(1, 6);
    tri([bx - 1, by - 2], [ri(1, 4), wy], [bx - 2, by + 3], "a");
    tri([bx + 1, by - 2], [ri(25, 28), wy], [bx + 2, by + 3], "a");
    limb(bx - 1, by - 2, ri(1, 4), wy, 0.6, 0.3, "b");
    ell(bx, by, brx, bry, "b");
    hx = bx + 2; hy = by - bry - 2; hrx = ri(2, 3); hry = 2;
    ell(hx, hy, hrx, hry, "b");
    if (chance(0.6)) tri([hx + hrx, hy], [hx + hrx + ri(3, 5), hy + 1], [hx + hrx, hy + 1], "l");
    for (const x of [bx - 1, bx + 1]) { limb(x, by + bry, x, GROUND - 2, 0.5, 0.5, "b"); legs.push(x); }
    tailEnd = [bx - 2, by + bry + 3]; limb(bx, by + bry - 1, ...tailEnd, 1, 0, "b");
  } else { // serpent
    const amp = ri(2, 4), ph = R() * 6, base = GROUND - 4;
    let px = 3, py = base;
    for (let x = 3; x <= 21; x++) {
      const y = base + Math.sin(x / 3 + ph) * amp;
      limb(px, py, x, y, x < 6 ? 1 : 2.2, 2.2, "b");
      px = x; py = y;
    }
    bx = 12; by = base; brx = 9; bry = 2;
    hx = 23; hy = py - 3; hrx = 3; hry = ri(2, 3);
    limb(px, py, hx - 1, hy + 1, 2.2, 2, "b");
    ell(hx, hy, hrx, hry, "b");
    ell(hx + hrx, hy + 1, 1, 1, "b");
  }

  // ---------- черево й візерунок
  if (kind !== "serpent") ell(bx, by + bry * 0.45, brx * 0.7, bry * 0.5, "l", ["b"]);
  else for (let x = 4; x < 22; x++) for (let y = 0; y < CH; y++) if (get(x, y) === "b" && get(x, y + 1) === "." && get(x, y + 2) === ".") set(x, y, "l");

  const pattern = pick(tier >= 2 ? ["spots", "stripes", "dots", "zigzag"] : ["none", "none", "spots", "stripes", "dots"]);
  for (let y = 0; y < CH; y++) for (let x = 0; x < CW; x++) {
    if (get(x, y) !== "b" || Math.abs(x - hx) + Math.abs(y - hy) < hrx + 1) continue;
    if (pattern === "spots" && (x * 7 + y * 13 + seed) % 9 === 0) { set(x, y, "p"); if (get(x + 1, y) === "b") set(x + 1, y, "p"); }
    if (pattern === "stripes" && x % 3 === 0 && y < by) set(x, y, "p");
    if (pattern === "dots" && (x + y * 2) % 5 === 0 && y < by + 1) set(x, y, "p");
    if (pattern === "zigzag" && (x + Math.abs((y % 4) - 2)) % 4 === 0 && y < by + 1) set(x, y, "p");
  }

  // ---------- мутації
  const top = (x) => { for (let y = 0; y < CH; y++) if ("bpl".includes(get(x, y))) return y; return null; };
  const traits = {
    horns() { const n = ri(1, 3); for (let i = 0; i < n; i++) { const x = hx - 1 + i * 2, t = top(x) ?? hy - hry; tri([x - 1, t], [x + 1, t], [x + ri(-1, 1), t - ri(2, 4)], "a"); } },
    spikes() { const big = chance(0.4); for (let x = bx - brx + 2; x < bx + brx - 1; x += big ? 3 : 2) { const t = top(x); if (t != null) tri([x - (big ? 1.5 : 1), t], [x + (big ? 1.5 : 1), t], [x, t - (big ? 3 : 2)], "a"); } },
    crest() { limb(hx, hy - hry, hx - ri(4, 6), hy - hry - ri(2, 4), 1, 0.5, "a"); },
    frill() { ell(hx - hrx, hy, hrx + 1, hry + 2, "a", ["."]); },
    antenna() { const x = hx + 1, t = hy - hry; limb(x, t, x + ri(-2, 2), t - ri(3, 5), 0.3, 0.3, "a"); ell(x + 1, t - 5, 1, 1, "y"); },
    wings() { if (kind !== "flyer") { const t = by - bry; tri([bx - 2, t + 1], [bx - ri(5, 8), t - ri(4, 7)], [bx + 2, t + 1], "a", ["."]); } },
    club() { if (tailEnd) ell(tailEnd[0], tailEnd[1], 1.6, 1.4, "a"); },
    fangs() { set(hx + hrx, hy + 2, "w"); set(hx + hrx - 2, hy + 2, "w"); },
    blush() { set(hx + 1, hy + 1, "r"); set(hx + 2, hy + 1, "r"); },
    mane() { for (let i = 0; i < 4; i++) ell(hx - hrx + 1 - i, hy - hry + i * 1.5, 1.2, 1.2, "a", [".", "b"]); },
  };
  const nTraits = [ri(1, 2), ri(2, 3), ri(3, 4), ri(4, 5)][tier];
  const pool = Object.keys(traits).sort(() => R() - 0.5).slice(0, nTraits);
  pool.forEach((t) => traits[t]());

  // ---------- очі й рот
  const eyeStyle = tier === 3 ? pick(["star", "big"]) : pick(["dot", "dot", "big", "sleepy", "tri", "cyclops"]);
  const ex = hx + 1, ey = hy - 1;
  const eye = (x, y) => {
    if (eyeStyle === "dot") set(x, y, "k");
    else if (eyeStyle === "sleepy") { set(x, y, "k"); set(x + 1, y, "k"); }
    else if (eyeStyle === "star") { set(x, y, "y"); set(x, y - 1, "s"); set(x - 1, y, "s"); }
    else { set(x, y, "w"); set(x + 1, y, "k"); set(x, y + 1, "k"); set(x + 1, y + 1, "k"); }
  };
  if (eyeStyle === "tri") { eye(ex - 1, ey); eye(ex + 1, ey - 1); eye(ex + 1, ey + 1); }
  else if (eyeStyle === "cyclops") { set(ex, ey, "w"); set(ex + 1, ey, "w"); set(ex, ey + 1, "k"); set(ex + 1, ey + 1, "k"); }
  else eye(ex, ey);
  if (chance(0.6)) { set(hx + hrx, hy + 1, "k"); if (chance(0.5)) set(hx + hrx - 1, hy + 2, "k"); }

  // ---------- аксесуари
  const accChance = [0.2, 0.4, 0.65, 1][tier];
  let acc = null;
  if (chance(accChance)) {
    acc = tier === 3 ? pick(["crown", "halo", "crown"]) : pick(["tophat", "cap", "glasses", "bow", "flower", "scarf", "halo"]);
    const t = hy - hry;
    if (acc === "crown") { for (let x = hx - 2; x <= hx + 2; x++) { set(x, t - 1, "y"); set(x, t - 2, "y"); } set(hx - 2, t - 3, "y"); set(hx, t - 3, "y"); set(hx + 2, t - 3, "y"); set(hx, t - 2, "r"); }
    if (acc === "halo") for (let x = hx - 2; x <= hx + 2; x++) set(x, t - 3, "y");
    if (acc === "tophat") { for (let x = hx - 3; x <= hx + 3; x++) set(x, t, "x"); for (let y = t - 4; y < t; y++) for (let x = hx - 2; x <= hx + 2; x++) set(x, y, y === t - 1 ? "r" : "x"); }
    if (acc === "cap") { for (let x = hx - 2; x <= hx + 2; x++) { set(x, t, "r"); set(x, t - 1, "r"); } for (let x = hx + 3; x <= hx + 5; x++) set(x, t, "r"); }
    if (acc === "glasses") { for (let x = ex - 2; x <= ex + 3; x++) set(x, ey, "x"); set(ex - 1, ey + 1, "x"); set(ex + 2, ey + 1, "x"); }
    if (acc === "bow") { set(hx - 2, t, "r"); set(hx - 3, t - 1, "r"); set(hx - 1, t - 1, "r"); set(hx - 3, t + 1, "r"); set(hx - 1, t + 1, "r"); }
    if (acc === "flower") { set(hx, t - 2, "y"); set(hx - 1, t - 1, "r"); set(hx + 1, t - 1, "r"); set(hx, t, "r"); set(hx, t - 1, "y"); }
    if (acc === "scarf") { limb(hx - 3, hy + hry + 1, hx + 1, hy + hry + 1, 0.8, 0.8, "r", ["b", "l", "p", "."]); limb(hx - 3, hy + hry + 1, hx - 5, hy + hry + 4, 0.5, 0.5, "r", ["."]); }
  }

  // ---------- контур, обʼєм, іскри
  const solid = (c) => c !== "." && c !== "o" && c !== "s";
  const out = g.map((row) => row.slice());
  for (let y = 0; y < CH; y++) for (let x = 0; x < CW; x++)
    if (g[y][x] === "." && [[1, 0], [-1, 0], [0, 1], [0, -1]].some(([dx, dy]) => solid(get(x + dx, y + dy)))) out[y][x] = "o";
  for (let y = 0; y < CH; y++) for (let x = 0; x < CW; x++) {
    if (out[y][x] !== "b") continue;
    if (out[y + 1]?.[x] === "o") out[y][x] = "d";
    else if (out[y - 1]?.[x] === "o" && (x + y) % 2 === 0) out[y][x] = "h";
  }
  if (tier === 3) for (let i = 0; i < 6; i++) { const x = ri(0, CW - 1), y = ri(0, 10); if (out[y][x] === ".") out[y][x] = "s"; }

  // центрування по горизонталі
  let minX = CW, maxX = 0;
  out.forEach((row) => row.forEach((c, x) => { if (c !== ".") { minX = Math.min(minX, x); maxX = Math.max(maxX, x); } }));
  const shift = Math.round((CW - 1 - maxX - minX) / 2);
  const rows = out.map((row) => { const r = Array(CW).fill("."); row.forEach((c, x) => { if (inb(x + shift, 0)) r[x + shift] = c; }); return r.join(""); });

  return { rows, colors: palette(R, tier), name: makeName(R, tier), lore: makeLore(R), kind, acc };
}

// ---------- кольори
function hsl(h, s, l) {
  h = ((h % 360) + 360) % 360; s = Math.min(100, s) / 100; l /= 100;
  const f = (n) => { const k = (n + h / 30) % 12; return l - s * Math.min(l, 1 - l) * Math.max(-1, Math.min(k - 3, 9 - k, 1)); };
  return "#" + [f(0), f(8), f(4)].map((v) => Math.round(v * 255).toString(16).padStart(2, "0")).join("");
}

function mix(c1, c2, t) {
  const p = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  const a = p(c1), b = p(c2);
  return "#" + a.map((v, i) => Math.round(v + (b[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

const LEGEND = [
  { b: "#F2B632", l: "#FFF0B8", p: "#E08A12", a: "#FFF6D5", o: "#3D2603" },
  { b: "#6A3DE8", l: "#E0A3FF", p: "#3DF5FF", a: "#FF7AF2", o: "#120A2E" },
  { b: "#1E1B24", l: "#FF6A3D", p: "#FF3D3D", a: "#FFB000", o: "#000000" },
  { b: "#7DF2C8", l: "#E9FFF7", p: "#5AA9FF", a: "#C38BFF", o: "#0B2A2A" },
  { b: "#F5F7FA", l: "#FFFFFF", p: "#AFC6FF", a: "#7DE3FF", o: "#1B2340" },
];

function palette(R, tier) {
  let c;
  if (tier === 3) c = { ...LEGEND[Math.floor(R() * LEGEND.length)] };
  else {
    const h = R() * 360;
    const s = [38, 58, 78][tier] + R() * 10;
    const l = 50 + R() * 10;
    const ah = h + (tier === 0 ? 30 + R() * 30 : 150 + R() * 60);
    c = { b: hsl(h, s, l), l: hsl(h + 20, s * 0.7, 84), p: hsl(h - 10, s, l - 16), a: hsl(ah, s + 5, 55), o: hsl(h, 45, 11) };
  }
  return { ...c, d: mix(c.b, "#000000", 0.28), h: mix(c.b, "#ffffff", 0.35),
           w: "#FFFFFF", k: c.o, r: "#FF6B8B", x: "#22242A", y: "#FFD447", s: "#FFF4B0" };
}

// ---------- імʼя й характер
const N1 = ["Бур", "Хрум", "Тик", "Шмя", "Грім", "Пух", "Кво", "Ляп", "Дзин", "Мур", "Фі", "Крак", "Жу", "Ням", "Буль", "Шур", "Ґо", "Тро", "Хо", "Зум", "Плю", "Брум", "Ці", "Гам"];
const N2 = ["", "ко", "ли", "ра", "бо", "зя", "ма", "ні", "ту", "ше", "ри", "до"];
const N3 = ["завр", "дон", "рекс", "птер", "нікс", "цератопс", "лонг", "зубик", "тон", "барс", "шлеп", "мусь"];
const EPI = ["Сонний", "Космічний", "Нічний", "Вогняний", "Кришталевий", "Туманний", "Ранковий", "Грозовий", "Шовковий", "Невидимий", "Мудрий", "Квантовий"];
const LOVES = ["ранні підйоми", "холодний душ", "борщ о 7 ранку", "списки справ", "тишу на світанку", "закреслювати пункти", "довгі прогулянки", "запах кави", "дедлайни, що вже здані", "чисті столи", "книжки з закладками", "дощ за вікном", "кашу з ягодами", "8 годин сну"];
const FEARS = ["понеділків", "будильника о 5:00", "нескінченної стрічки", "фрази «почну завтра»", "зниклого вайфаю", "немитого посуду", "100 вкладок у браузері", "холодної кави", "непрочитаних повідомлень", "розрядженого телефону"];
const POWERS = ["встає з першого будильника", "чує, коли ти відкладаєш справи", "перетворює звіти на XP", "читає 100 сторінок за вечір", "ніколи не пропускає тренування", "вміє казати «ні» відволіканням", "спить рівно 8 годин", "робить найважче зранку"];

function makeName(R, tier) {
  const p = (a) => a[Math.floor(R() * a.length)];
  let n = p(N1) + p(N2) + p(N3);
  if (tier >= 2) n = `${p(EPI)} ${n}`;
  return n;
}

function makeLore(R) {
  const p = (a) => a[Math.floor(R() * a.length)];
  return { loves: p(LOVES), fears: p(FEARS), power: p(POWERS) };
}

// ---------- рендер
function pixelSVG(rows, colors, { extra = [], extraColor, eyeClass = false } = {}) {
  const w = Math.max(...rows.map((r) => r.length)), h = rows.length;
  const groups = {};
  rows.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      const ch = row[x];
      if (ch === ".") { x++; continue; }
      let len = 1;
      while (row[x + len] === ch) len++;
      (groups[ch] ||= []).push(`M${x} ${y}h${len}v1h-${len}z`);
      x += len;
    }
  });
  let paths = Object.entries(groups).map(([ch, d]) => {
    const cls = eyeClass && (ch === "w" || ch === "k") ? ' class="eye"' : ch === "s" ? ' class="spark"' : "";
    return `<path${cls} fill="${colors[ch] || colors.o}" d="${d.join("")}"/>`;
  }).join("");
  if (extra.length) paths += `<path fill="${extraColor}" d="${extra.map(([x, y]) => `M${x} ${y}h1v1h-1z`).join("")}"/>`;
  return `<svg viewBox="0 0 ${w} ${h}" shape-rendering="crispEdges" xmlns="http://www.w3.org/2000/svg">${paths}</svg>`;
}

function creatureSVG(c) { return pixelSVG(c.rows, c.colors, { eyeClass: true }); }

const EGG = [
  "....oooo....",
  "...obbbbo...",
  "..obbabbbo..",
  ".obbbbbbabo.",
  ".obabbbbbbo.",
  "obbbbbbabbbo",
  "obbbbbbbbbbo",
  "obbabbbbbbbo",
  "obbbbbbbabbo",
  "obbbbbbbbbbo",
  ".obbbabbbbo.",
  ".obbbbbbbbo.",
  "..obbbbbbo..",
  "...oooooo...",
];
const CRACKS = [
  [],
  [[5, 4], [6, 5], [5, 6]],
  [[5, 4], [6, 5], [5, 6], [6, 7], [7, 8], [4, 7], [3, 8]],
  [[5, 4], [6, 5], [5, 6], [6, 7], [7, 8], [4, 7], [3, 8], [8, 9], [2, 9], [6, 3], [7, 2], [8, 6], [9, 5]],
];

function eggSVG(rarity, stage = 0) {
  const colors = { o: "#2A241A", b: "#F3E9D2", a: RARITY_COLOR[rarity] || RARITY_COLOR.common };
  return pixelSVG(EGG, colors, { extra: CRACKS[Math.min(stage, 3)], extraColor: "#2A241A" });
}

if (typeof module !== "undefined") module.exports = { makeCreature, creatureSVG, eggSVG, RARITY_COLOR };
