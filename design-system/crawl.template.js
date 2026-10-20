// ds-inventory: crawl template for `playwright-cli run-code --filename=<filled copy>`.
//
// run-code evaluates ONE function expression that receives the Playwright `page`.
// It cannot import, require or take arguments, so copy this file into the inventory
// folder as crawl.js and fill the CONFIG block and ROUTES there. Never edit the template.
//
// Run (session already open, see CONVENTIONS.md):
//   playwright-cli -s=dds --raw run-code --filename=<inventory>/crawl.js > <inventory>/inventory.json
//
// Output (schema ds-inventory/1): per-state element counts, style values aggregated by
// logical property (each element counts once per distinct value of a property, so a box
// with the same border on four sides counts once), how many of those instances are the
// browser's default rather than authored (`ua`), and text/background pairs with the text
// sizes and weights drawn on them. States that answered HTTP >= 400 are listed in `errors`.

async (page) => {
  // ---- CONFIG: fill in the copy --------------------------------------------
  const CONFIG = {
    baseUrl: '__BASE_URL__',          // origin, or the app's base path, e.g. 'https://staging.example.com/app/'
    commit: '__COMMIT__',             // `git rev-parse HEAD` of the product repo
    outDir: '__OUT_DIR__',            // absolute path of <inventory>/screenshots (where files are written)
    shotsRel: 'screenshots',          // how inventory.json refers to them: relative to inventory.json
    theme: 'default',                 // label for the theme this crawl covers; one inventory per theme
    colorScheme: null,                // 'light' | 'dark' | null: emulated before every state
    viewports: [{ name: 'desktop', width: 1440, height: 900 }],
    screenshots: true,
    settleMs: 300,                    // wait after load / state steps
    maxSamples: 3,                    // sample selectors kept per value
  };
  // Each route: { name, path, states: [{ name, steps: async (page) => {...} }] }.
  // A route with no `states` is crawled once as state 'default'.
  // `steps` bodies come from `playwright-cli recording-stop` output, trimmed to the
  // actions that reach the state (open a modal, submit an empty form, hover, focus, ...).
  const ROUTES = [
    // __ROUTES__
  ];
  // -------------------------------------------------------------------------

  const extract = (maxSamples) => {
    // logical property -> computed longhands it is read from
    const LOGICAL = {
      color: { color: ['color'], 'background-color': ['background-color'],
        'border-color': ['border-top-color', 'border-right-color', 'border-bottom-color', 'border-left-color'],
        'outline-color': ['outline-color'], fill: ['fill'], stroke: ['stroke'] },
      typography: { 'font-family': ['font-family'], 'font-size': ['font-size'], 'font-weight': ['font-weight'],
        'line-height': ['line-height'], 'letter-spacing': ['letter-spacing'], 'text-transform': ['text-transform'] },
      spacing: { margin: ['margin-top', 'margin-right', 'margin-bottom', 'margin-left'],
        padding: ['padding-top', 'padding-right', 'padding-bottom', 'padding-left'],
        gap: ['row-gap', 'column-gap'] },
      radius: { 'border-radius': ['border-top-left-radius', 'border-top-right-radius',
        'border-bottom-right-radius', 'border-bottom-left-radius'] },
      border: { 'border-width': ['border-top-width', 'border-right-width', 'border-bottom-width', 'border-left-width'] },
      elevation: { 'box-shadow': ['box-shadow'] },
      motion: { 'transition-duration': ['transition-duration'],
        'transition-timing-function': ['transition-timing-function'] },
    };
    // Values that mean "nothing set" for the property. 'normal' is a real line-height.
    const BORING = new Set(['', 'none', '0px', '0s', 'auto', 'rgba(0, 0, 0, 0)', 'transparent', 'ease', 'start']);
    const boring = (prop, v) => BORING.has(v) || (v === 'normal' && prop !== 'line-height');
    const SIDES = ['top', 'right', 'bottom', 'left'];
    // Properties that do not inherit, plus what browsers set on form controls: an instance
    // equal to the browser's default for that tag was not authored, so it is counted in `ua`.
    const FORM = new Set(['button', 'input', 'select', 'textarea']);
    const UA_PROPS = new Set(['background-color', 'border-color', 'border-width', 'border-radius', 'margin',
      'padding', 'gap', 'box-shadow', 'outline-color']);
    const UA_FORM_PROPS = new Set(['font-family', 'font-size', 'font-weight', 'color', 'letter-spacing']);

    const sel = (el) => {
      let s = el.tagName.toLowerCase();
      if (el.id) s += '#' + el.id;
      const cls = typeof el.className === 'string' ? el.className.trim().split(/\s+/).filter(Boolean) : [];
      if (cls.length) s += '.' + cls.slice(0, 3).join('.');
      return s;
    };
    const visible = (el, cs) => cs.display !== 'none' && cs.visibility !== 'hidden'
      && el.getClientRects().length > 0;
    const hasOwnText = (el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    const effectiveBg = (el) => {
      for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
        const bg = getComputedStyle(n).backgroundColor;
        if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return bg;
      }
      return 'canvas';
    };
    const read = (el, cs, logical, longhands) => {
      const out = new Set();
      longhands.forEach((p, i) => {
        if (logical === 'border-color' || logical === 'border-width') {
          const side = SIDES[i];
          if (cs.getPropertyValue(`border-${side}-style`) === 'none'
            || cs.getPropertyValue(`border-${side}-width`) === '0px') return;
        }
        if (logical === 'outline-color' && cs.outlineStyle === 'none') return;
        if ((logical === 'fill' || logical === 'stroke') && !(el instanceof SVGElement)) return;
        const v = cs.getPropertyValue(p).trim();
        if (!boring(logical, v)) out.add(v);
      });
      return out;
    };

    const elementsList = [...document.querySelectorAll('body, body *')];

    // Browser defaults per tag (+type), from an unstyled document in a hidden iframe.
    const frame = document.createElement('iframe');
    frame.setAttribute('aria-hidden', 'true');
    frame.style.cssText = 'position:absolute;left:-10000px;top:0;width:800px;height:600px;border:0;visibility:hidden';
    document.body.appendChild(frame);
    const fdoc = frame.contentDocument;
    fdoc.open(); fdoc.write('<!doctype html><html><head></head><body></body></html>'); fdoc.close();
    const uaCache = new Map();
    const uaDefaults = (el) => {
      const tag = el.tagName.toLowerCase();
      const type = el.getAttribute && el.getAttribute('type');
      const key = tag + (type ? `[type=${type}]` : '');
      if (uaCache.has(key)) return uaCache.get(key);
      let d = null;
      try {
        const probe = fdoc.createElementNS(el.namespaceURI || 'http://www.w3.org/1999/xhtml', tag);
        if (type) probe.setAttribute('type', type);
        if (tag === 'body') { d = fdoc.defaultView.getComputedStyle(fdoc.body); } else {
          fdoc.body.appendChild(probe);
          d = fdoc.defaultView.getComputedStyle(probe);
        }
        const snap = {};
        for (const group of Object.values(LOGICAL)) {
          for (const [logical, longhands] of Object.entries(group)) snap[logical] = read(probe, d, logical, longhands);
        }
        // Does the default border/outline color follow `color` (currentColor)? Probe with a sentinel.
        const before = probe.style.color;
        probe.style.color = 'rgb(1, 2, 3)';
        const d2 = fdoc.defaultView.getComputedStyle(probe);
        snap._borderCurrent = d2.borderTopColor === 'rgb(1, 2, 3)';
        snap._outlineCurrent = d2.outlineColor === 'rgb(1, 2, 3)';
        probe.style.color = before;
        d = snap;
      } catch (e) { d = null; }
      uaCache.set(key, d);
      return d;
    };
    const isUa = (el, cs, logical, v) => {
      const tag = el.tagName.toLowerCase();
      if (!UA_PROPS.has(logical) && !(FORM.has(tag) && UA_FORM_PROPS.has(logical))) return false;
      const d = uaDefaults(el);
      if (!d) return false;
      // Where the browser's default border or outline color is currentColor, the default
      // for this element is its own text color.
      if (logical === 'border-color' && d._borderCurrent) return v === cs.color;
      if (logical === 'outline-color' && d._outlineCurrent) return v === cs.color;
      return !!d[logical] && d[logical].has(v);
    };

    const values = {};   // group -> logical property -> value -> {count, ua, samples[]}
    const pairs = {};    // "fg | bg" -> {count, samples[], texts: [{fontSize, fontWeight}]}
    let elements = 0;
    const bump = (bucket, key, s) => {
      const e = bucket[key] || (bucket[key] = { count: 0, ua: 0, samples: [] });
      e.count++;
      if (e.samples.length < maxSamples && !e.samples.includes(s)) e.samples.push(s);
      return e;
    };
    for (const el of elementsList) {
      const cs = getComputedStyle(el);
      if (!visible(el, cs)) continue;
      elements++;
      const s = sel(el);
      for (const [group, props] of Object.entries(LOGICAL)) {
        for (const [logical, longhands] of Object.entries(props)) {
          for (const v of read(el, cs, logical, longhands)) {
            const g = values[group] || (values[group] = {});
            const e = bump(g[logical] || (g[logical] = {}), v, s);
            if (isUa(el, cs, logical, v)) e.ua++;
          }
        }
      }
      if (hasOwnText(el)) {
        const e = bump(pairs, `${cs.color} | ${effectiveBg(el)}`, s);
        delete e.ua;
        const t = { fontSize: cs.fontSize, fontWeight: Number(cs.fontWeight) || 400 };
        e.texts = e.texts || [];
        if (!e.texts.some((x) => x.fontSize === t.fontSize && x.fontWeight === t.fontWeight)) e.texts.push(t);
      }
    }
    frame.remove();
    return { elements, values, pairs };
  };

  // Merge one state's extraction into the global inventory.
  const inventory = {
    meta: { schema: 'ds-inventory/1', generatedAt: new Date().toISOString(), baseUrl: CONFIG.baseUrl,
      commit: CONFIG.commit, theme: CONFIG.theme, colorScheme: CONFIG.colorScheme, viewports: CONFIG.viewports },
    states: [], errors: [], values: {}, pairs: {} };
  const merge = (target, src, stateId) => {
    for (const [k, e] of Object.entries(src)) {
      const t = target[k] || (target[k] = e.texts ? { count: 0, states: [], samples: [] }
        : { count: 0, ua: 0, states: [], samples: [] });
      t.count += e.count;
      if (e.ua !== undefined) t.ua += e.ua;
      if (!t.states.includes(stateId)) t.states.push(stateId);
      for (const x of e.samples) if (t.samples.length < CONFIG.maxSamples && !t.samples.includes(x)) t.samples.push(x);
      if (e.texts) {
        t.texts = t.texts || [];
        for (const x of e.texts) {
          if (!t.texts.some((y) => y.fontSize === x.fontSize && y.fontWeight === x.fontWeight)) t.texts.push(x);
        }
      }
    }
  };

  const safe = (s) => s.replace(/[^a-z0-9_-]+/gi, '-');
  for (const vp of CONFIG.viewports) {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    for (const route of ROUTES) {
      const states = route.states && route.states.length ? route.states : [{ name: 'default' }];
      for (const state of states) {
        const id = `${vp.name}/${route.name}/${state.name}`;
        try {
          // Undo whatever the previous state's steps changed.
          await page.context().setOffline(false);
          await page.unrouteAll({ behavior: 'ignoreErrors' });
          await page.emulateMedia({ colorScheme: CONFIG.colorScheme, reducedMotion: null });
          const resp = await page.goto(new URL(route.path, CONFIG.baseUrl).href, { waitUntil: 'load' });
          const status = resp ? resp.status() : null;
          if (status && status >= 400) inventory.errors.push({ id, error: `HTTP ${status}` });
          await page.waitForTimeout(CONFIG.settleMs);
          if (state.steps) { await state.steps(page); await page.waitForTimeout(CONFIG.settleMs); }
          const r = await page.evaluate(extract, CONFIG.maxSamples);
          let shot = null;
          if (CONFIG.screenshots) {
            const file = `${safe(vp.name)}--${safe(route.name)}--${safe(state.name)}.png`;
            await page.screenshot({ path: `${CONFIG.outDir}/${file}`, fullPage: true });
            shot = `${CONFIG.shotsRel}/${file}`;
          }
          inventory.states.push({ id, url: page.url(), status, elements: r.elements, screenshot: shot });
          for (const [group, props] of Object.entries(r.values)) {
            const g = inventory.values[group] || (inventory.values[group] = {});
            for (const [p, vals] of Object.entries(props)) merge(g[p] || (g[p] = {}), vals, id);
          }
          merge(inventory.pairs, r.pairs, id);
        } catch (err) {
          inventory.errors.push({ id, error: String(err && err.message || err).slice(0, 500) });
        }
      }
    }
  }

  // Summary: distinct values per property, most frequent first in the detail.
  inventory.summary = {};
  for (const [group, props] of Object.entries(inventory.values)) {
    for (const [p, vals] of Object.entries(props)) {
      inventory.summary[p] = Object.keys(vals).length;
      props[p] = Object.fromEntries(Object.entries(vals).sort((a, b) => b[1].count - a[1].count));
    }
  }
  inventory.summary.colorPairs = Object.keys(inventory.pairs).length;
  return inventory;
}
