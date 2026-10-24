/* Read-only browser acceptance tests for a generated, offline HTML artifact. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function check(name, engine, executablePath, viewport, html, output) {
  const browser = await engine.launch({headless:true, executablePath});
  try {
    const page = await browser.newPage({viewport});
    const errors = [], external = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', request => { if (/^https?:/i.test(request.url())) external.push(request.url()); });
    await page.goto(pathToFileURL(html).href);
    await page.waitForFunction(() => window.trafficLab?.bundle?.runs.length);
    const bundle = await page.evaluate(() => window.trafficLab.bundle);
    assert.match(await page.locator('#bundle-label').innerText(), /Synthetic demonstration, not calibrated to View Royal/);
    assert.equal(await page.locator('canvas').count(), 2);
    assert.ok((await page.locator('#left-title').innerText()).length < 40, 'Use concise, distinct scenario titles');
    assert.match(await page.locator('#left-changes').innerText(), /North .* s/);
    assert.match(await page.locator('#right-changes').innerText(), /North .* s/);
    assert.equal(await page.locator('details#definitions-panel').getAttribute('open'), null);
    assert.equal(await page.locator('details#provenance-panel').getAttribute('open'), null);
    if (bundle.runs.every(r=>r.diagnostics.valid) && bundle.runs.some(r=>r.metrics.not_inserted || r.metrics.active)) {
      assert.match(await page.locator('#comparison-warning').innerText(), /Unfinished demand/);
    }
    const control = page.locator('#proposal-select');
    for (const proposal of bundle.runs.filter(r => r.variant !== 'baseline')) {
      await control.selectOption(proposal.run_id);
      assert.equal(await page.evaluate(() => window.trafficLab.state.right.variant), proposal.variant);
      for (const [label, key] of [['Requested','requested'], ['Completed','completed'], ['Active at horizon','active'], ['Not inserted','not_inserted'], ['Removed','removed']]) {
        const row = page.locator('#summary-body tr').filter({has:page.getByRole('rowheader', {name:label, exact:true})});
        const cells = await row.locator('td').allTextContents();
        const left = bundle.runs.find(r=>r.variant==='baseline') || bundle.runs[0];
        assert.deepEqual(cells, [String(left.metrics[key]),String(proposal.metrics[key])]);
      }
    }
    const seek = page.locator('#seek');
    const maximum = Number(await seek.getAttribute('max'));
    await seek.focus();
    await page.keyboard.press('End');
    assert.equal(await page.evaluate(()=>window.trafficLab.state.frame), maximum);
    await page.keyboard.press('Home');
    assert.equal(await page.evaluate(()=>window.trafficLab.state.frame), 0);
    if(maximum > 0) {
      await page.locator('#speed-select').selectOption('4');
      await page.getByRole('button',{name:'Play',exact:true}).click();
      await page.waitForFunction(()=>window.trafficLab.state.frame > 0,{},{timeout:5000});
      await page.getByRole('button',{name:'Pause',exact:true}).click();
      const paused = await page.evaluate(()=>window.trafficLab.state.frame);
      await page.waitForTimeout(350);
      assert.equal(await page.evaluate(()=>window.trafficLab.state.frame), paused);
    }
    const layout = await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth, header:getComputedStyle(document.querySelector('header')).position}));
    assert.ok(layout.scroll <= layout.width, `${name}: page overflows ${layout.scroll}/${layout.width}`);
    assert.ok(!['sticky','fixed'].includes(layout.header), 'Header must scroll away');
    const main = bundle.runs.find(r=>r.variant==='rebalanced');
    if(main) await control.selectOption(main.run_id);
    await seek.evaluate((node,value)=>{node.value=String(value);node.dispatchEvent(new Event('input',{bubbles:true}));},Math.floor(maximum*.6));
    await page.screenshot({path:path.join(output,`${name}.png`),fullPage:true});
    assert.deepEqual(errors,[]);
    assert.deepEqual(external,[]);
    const state = await page.evaluate(()=>({frame:window.trafficLab.state.frame,time:window.trafficLab.state.left.frames[window.trafficLab.state.frame].t}));
    return {name,status:'PASS',browser_version:await browser.version(),viewport,layout,errors,external_requests:external,state};
  } finally { await browser.close(); }
}

(async()=>{
  const html=path.resolve(process.argv[2] || 'runs/demo/traffic-lab-demo.html');
  const output=path.resolve(process.argv[3] || 'runs/browser-qa');
  fs.mkdirSync(output,{recursive:true});
  const receipt=[];
  receipt.push(await check('chromium-desktop',playwright.chromium,playwright.chromium.executablePath(),{width:1440,height:1000},html,output));
  receipt.push(await check('chromium-mobile',playwright.chromium,playwright.chromium.executablePath(),{width:390,height:844},html,output));
  if(process.env.WEBKIT_EXECUTABLE) receipt.push(await check('webkit-mobile',playwright.webkit,process.env.WEBKIT_EXECUTABLE,{width:390,height:844},html,output));
  fs.writeFileSync(path.join(output,'receipt.json'),JSON.stringify({artifact:html,checks:receipt},null,2));
  console.log(JSON.stringify(receipt,null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});
