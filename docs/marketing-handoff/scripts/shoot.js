// node shoot.js <baseUrl> <outDir> <path:name[:width[:theme]]> ...
const { chromium } = require('playwright');
(async () => {
  const [base, out, ...specs] = process.argv.slice(2);
  const browser = await chromium.launch();
  const errors = [];
  for (const spec of specs) {
    const [path, name, width = '1440', theme = 'light'] = spec.split('|');
    const ctx = await browser.newContext({ viewport: { width: parseInt(width), height: 900 }, colorScheme: theme === 'dark' ? 'dark' : 'light', deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(`${name}: ${e.message}`));
    page.on('console', m => { if (m.type() === 'error') errors.push(`${name} console: ${m.text()}`); });
    await page.goto(base + path, { waitUntil: 'networkidle' });
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (overflow > 0) errors.push(`${name}: horizontal overflow ${overflow}px`);
    await page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
    await ctx.close();
  }
  await browser.close();
  console.log(errors.length ? errors.join('\n') : 'no page errors');
})();
