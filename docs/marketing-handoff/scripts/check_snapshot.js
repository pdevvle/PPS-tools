// One pass over the demo copy: every page loads cleanly at desktop and phone width,
// links move between saved pages, and write actions answer with the read-only note.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [base, dir, out] = process.argv.slice(2);
  const pages = fs.readdirSync(dir).filter(f => f.endsWith('.html'));
  const browser = await chromium.launch();
  const problems = [];
  for (const [width, scheme] of [[1440, 'light'], [390, 'dark']]) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: scheme });
    const page = await ctx.newPage();
    page.on('pageerror', e => problems.push(`${width} ${page.url()}: ${e.message}`));
    page.on('console', m => { if (m.type() === 'error') problems.push(`${width} ${page.url()} console: ${m.text()}`); });
    for (const f of pages) {
      await page.goto(`${base}/${f}`, { waitUntil: 'load' });
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (over > 0) problems.push(`${width} ${f}: ${over}px horizontal overflow`);
    }
    await ctx.close();
  }
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await ctx.newPage();
  const step = async (name, fn) => { try { await fn(); console.log('ok   ' + name); } catch (e) { problems.push(`${name}: ${e.message.split('\n')[0]}`); console.log('FAIL ' + name); } };
  const toast = async () => (await page.locator('.toast').last().textContent({ timeout: 3000 })).trim();
  await page.goto(`${base}/index.html`, { waitUntil: 'load' });
  await page.screenshot({ path: `${out}/index.png` });
  await step('nav link to Campaigns', async () => {
    await page.click('nav a:has-text("Campaigns")');
    await page.waitForURL(/campaigns\.html$/);
  });
  await step('range preset on Campaigns', async () => {
    await page.click('a:has-text("Last 7 days")');
    await page.waitForURL(/campaigns-7d\.html$/);
  });
  await step('pause answers read-only', async () => {
    await page.locator('button:has-text("Pause")').first().click();
    const t = await toast();
    if (!t.includes('read-only')) throw new Error('toast was: ' + t);
  });
  await step('custom range form answers', async () => {
    await page.click('form.filters button[type=submit]');
    const t = await toast();
    if (!t.includes('preset ranges')) throw new Error('toast was: ' + t);
  });
  await step('export link answers', async () => {
    await page.goto(`${base}/index.html`, { waitUntil: 'load' });
    await page.click('a:has-text("Export CSV")');
    const t = await toast();
    if (!t.includes('CSV export')) throw new Error('toast was: ' + t);
  });
  await step('rule preview (dry run) shows matches', async () => {
    await page.goto(`${base}/automation.html`, { waitUntil: 'load' });
    await page.locator('.run-rules[data-dry="1"]').first().click();
    await page.locator('#outcomes .banner').waitFor({ timeout: 3000 });
    console.log('     ' + (await page.locator('#outcomes .banner p').first().textContent()));
    await page.screenshot({ path: `${out}/automation.png`, fullPage: true });
  });
  await step('studio library loads and hands copy to the composer', async () => {
    await page.goto(`${base}/studio.html`, { waitUntil: 'load' });
    await page.click('.load-copy');
    await page.locator('#results .variant').first().waitFor({ timeout: 3000 });
    await page.screenshot({ path: `${out}/studio.png`, fullPage: true });
    await page.locator('button:has-text("Use in composer")').first().click();
    await page.waitForURL(/publish\.html$/);
    const body = await page.locator('#body').inputValue();
    if (!body) throw new Error('composer stayed empty');
  });
  await step('publish form answers read-only', async () => {
    await page.locator('input[name=targets]').first().check();
    await page.locator('#composer button[type=submit]').first().click();
    const t = await toast();
    if (!t.includes('read-only')) throw new Error('toast was: ' + t);
  });
  await step('calendar renders events', async () => {
    await page.goto(`${base}/publish-calendar.html`, { waitUntil: 'load' });
    const n = await page.locator('.calendar .ev').count();
    if (!n) throw new Error('no events');
  });
  await step('connections loads at phone width', async () => {
    await page.setViewportSize({ width: 390, height: 900 });
    await page.goto(`${base}/connections.html`, { waitUntil: 'load' });
    await page.screenshot({ path: `${out}/connections-390.png` });
  });
  await browser.close();
  console.log(problems.length ? 'PROBLEMS:\n' + problems.join('\n') : 'no problems');
})();
