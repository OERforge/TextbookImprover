// Made the renderings in renderings.json: npm install mathjax-full@3 @mathjax/src@4
// mathjax-node@2, then node make.js, then strip the SVG paths' d attributes.
// Renders two formulas with MathJax 2, 3, and 4, in CommonHTML and SVG, with
// and without the hidden MathML each version adds for screen readers.
const fs = require('fs');
const INLINE = 'x_a^b + \\frac{1}{2}';
const DISPLAY = '\\sqrt{k^2} = \\begin{cases} 4 & k=0 \\\\ 11 & k>0 \\end{cases}';
const LIMITS = '\\sum_{i=1}^{n} i + \\sqrt[3]{y}';
const out = {};
function v3v4(label, base) {
  const {mathjax} = require(base + '/js/mathjax.js');
  const {TeX} = require(base + '/js/input/tex.js');
  let packages;
  try { packages = require(base + '/js/input/tex/AllPackages.js').AllPackages; }
  catch (e) { require(base + '/js/input/tex/ams/AmsConfiguration.js'); packages = ['base', 'ams']; }
  const {CHTML} = require(base + '/js/output/chtml.js');
  const {SVG} = require(base + '/js/output/svg.js');
  const {liteAdaptor} = require(base + '/js/adaptors/liteAdaptor.js');
  const {RegisterHTMLHandler} = require(base + '/js/handlers/html.js');
  const {AssistiveMmlHandler} = require(base + '/js/a11y/assistive-mml.js');
  for (const jax of ['chtml', 'svg']) for (const assistive of [true, false]) {
    const adaptor = liteAdaptor();
    const handler = RegisterHTMLHandler(adaptor);
    if (assistive) AssistiveMmlHandler(handler);
    const doc = mathjax.document('', {InputJax: new TeX({packages}), OutputJax: jax === 'svg' ? new SVG({fontCache: 'local'}) : new CHTML()});
    const key = `${label}-${jax}-${assistive ? 'mml' : 'bare'}`;
    try {
      out[key] = [INLINE, DISPLAY, LIMITS].map((tex, i) => adaptor.outerHTML(doc.convert(tex, {display: i > 0})));
    } catch (e) { out[key] = ['ERROR ' + e.message]; }
    mathjax.handlers.unregister(handler);
  }
}
v3v4('mj3', 'mathjax-full');
try { v3v4('mj4', '@mathjax/src'); } catch (e) { out['mj4'] = ['ERROR ' + e.message]; }
const mj2 = require('mathjax-node');
mj2.start();
const jobs = [];
for (const [fmt, flag] of [['chtml', 'html'], ['svg', 'svg']]) for (const [tex, i] of [[INLINE, 0], [DISPLAY, 1], [LIMITS, 2]])
  jobs.push(mj2.typeset({math: tex, format: i ? 'TeX' : 'inline-TeX', [flag]: true, mml: true}).then(r => {
    (out[`mj2-${fmt}`] = out[`mj2-${fmt}`] || [])[i] = r[flag]; out['mj2-mml'] = out['mj2-mml'] || []; out['mj2-mml'][i] = r.mml; }));
Promise.all(jobs).then(() => { fs.writeFileSync('samples.json', JSON.stringify(out, null, 1)); console.log(Object.keys(out).map(k => `${k}: ${out[k].map(s => (s || '').length).join('/')}`).join('\n')); });
