// ds-inventory: crawl template for `playwright-cli run-code --filename=<filled copy>`.
//
// run-code evaluates ONE function expression that receives the Playwright `page`.
// It cannot import, require or take arguments, so copy this file to a scratch
// location and fill the CONFIG block in the copy. Never edit this template in place.
//
// Run:   playwright-cli --raw run-code --filename=<scratch>/crawl.js > <out>/inventory.json
// Output: JSON with per-state element counts, aggregated style values (count, states,
// sample selectors) and text/background color pairs. States that answered HTTP >= 400
// are listed in `errors`: an error page is real UI, but check it is the one you meant. Screenshots go to CONFIG.outDir.

async (page) => {
  // ---- CONFIG: fill in the scratch copy -----------------------------------
  const CONFIG = {
    baseUrl: '__BASE_URL__',          // e.g. 'https://staging.example.com'
    commit: '__COMMIT__',             // `git rev-parse HEAD` of the product repo
    outDir: '__OUT_DIR__',            // absolute path for screenshots
    viewports: [{ name: 'desktop', width: 1440, height: 900 }],
    screenshots: true,
    settleMs: 300,                    // wait after load / state steps
    maxSamples: 3,                    // sample selectors kept per value
  };
  // Each route: { name, path, states: [{ name, steps: async (page) => {...} }] }.
  // A route with no `states` is crawled once as state 'default'.
  // `steps` bodies come from `playwright-cli recording-stop` output, trimmed to the
  // actions that reach the state (open a modal, submit an empty form, ...).
  const ROUTES = [
    // __ROUTES__
  ];
  // -------------------------------------------------------------------------

  const extract = (maxSamples) => {
    const PROPS = {
      color: ['color', 'background-color', 'border-top-color', 'border-right-color',
        'border-bottom-color', 'border-left-color', 'outline-color', 'fill', 'stroke'],
      typography: ['font-family', 'font-size', 'font-weight', 'line-height', 'letter-spacing',
        'text-transform'],
      spacing: ['margin-top', 'margin-right', 'margin-bottom', 'margin-left', 'padding-top',
        'padding-right', 'padding-bottom', 'padding-left', 'row-gap', 'column-gap'],
      radius: ['border-top-left-radius', 'border-top-right-radius',
        'border-bottom-right-radius', 'border-bottom-left-radius'],
      border: ['border-top-width', 'border-right-width', 'border-bottom-width', 'border-left-width'],
      elevation: ['box-shadow'],
      motion: ['transition-duration', 'transition-timing-function'],
    };
    const BORING = new Set(['', 'none', 'normal', '0px', '0s', 'auto', 'rgba(0, 0, 0, 0)',
      'transparent', 'ease', 'start']);
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

    const values = {};   // group -> prop -> value -> {count, samples[]}
    const pairs = {};    // "fg | bg" -> {count, fontSizes:Set, samples[]}
    let elements = 0;
    const bump = (bucket, key, s) => {
      const e = bucket[key] || (bucket[key] = { count: 0, samples: [] });
      e.count++;
      if (e.samples.length < maxSamples && !e.samples.includes(s)) e.samples.push(s);
      return e;
    };
    for (const el of document.querySelectorAll('body, body *')) {
      const cs = getComputedStyle(el);
      if (!visible(el, cs)) continue;
      elements++;
      const s = sel(el);
      for (const [group, props] of Object.entries(PROPS)) {
        for (const p of props) {
          const v = cs.getPropertyValue(p).trim();
          if (BORING.has(v)) continue;
          // Border colors only count where the border is drawn.
          if (p.startsWith('border-') && p.endsWith('-color')) {
            const side = p.split('-')[1];
            if (cs.getPropertyValue(`border-${side}-style`) === 'none'
              || cs.getPropertyValue(`border-${side}-width`) === '0px') continue;
          }
          if (p === 'outline-color' && cs.outlineStyle === 'none') continue;
          if ((p === 'fill' || p === 'stroke') && !(el instanceof SVGElement)) continue;
          const g = values[group] || (values[group] = {});
          bump(g[p] || (g[p] = {}), v, s);
        }
      }
      if (hasOwnText(el)) {
        const e = bump(pairs, `${cs.color} | ${effectiveBg(el)}`, s);
        (e.fontSizes || (e.fontSizes = [])).includes(cs.fontSize) || e.fontSizes.push(cs.fontSize);
        if (Number(cs.fontWeight) >= 700) e.bold = true;
      }
    }
    return { elements, values, pairs };
  };

  // Merge one state's extraction into the global inventory.
  const inventory = {
    meta: { schema: 'ds-inventory/1', generatedAt: new Date().toISOString(), baseUrl: CONFIG.baseUrl,
      commit: CONFIG.commit, viewports: CONFIG.viewports },
    states: [], errors: [], values: {}, pairs: {} };
  const merge = (target, src, stateId) => {
    for (const [k, e] of Object.entries(src)) {
      const t = target[k] || (target[k] = { count: 0, states: [], samples: [] });
      t.count += e.count;
      if (!t.states.includes(stateId)) t.states.push(stateId);
      for (const x of e.samples) if (t.samples.length < CONFIG.maxSamples && !t.samples.includes(x)) t.samples.push(x);
      if (e.fontSizes) for (const f of e.fontSizes) (t.fontSizes || (t.fontSizes = [])).includes(f) || t.fontSizes.push(f);
      if (e.bold) t.bold = true;
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
          await page.emulateMedia({ colorScheme: null, reducedMotion: null });
          const resp = await page.goto(new URL(route.path, CONFIG.baseUrl).href, { waitUntil: 'load' });
          const status = resp ? resp.status() : null;
          if (status && status >= 400) inventory.errors.push({ id, error: `HTTP ${status}` });
          await page.waitForTimeout(CONFIG.settleMs);
          if (state.steps) { await state.steps(page); await page.waitForTimeout(CONFIG.settleMs); }
          const r = await page.evaluate(extract, CONFIG.maxSamples);
          let shot = null;
          if (CONFIG.screenshots) {
            shot = `${CONFIG.outDir}/${safe(vp.name)}--${safe(route.name)}--${safe(state.name)}.png`;
            await page.screenshot({ path: shot, fullPage: true });
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
