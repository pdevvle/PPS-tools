// End-to-end click-through of the Marketing Hub in demo mode.
const { chromium } = require('playwright');
const assert = (cond, msg) => { if (!cond) throw new Error('ASSERT: ' + msg); };

(async () => {
  const base = process.argv[2];
  const out = process.argv[3];
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  page.on('dialog', d => d.accept());
  const step = (s) => console.log('• ' + s);

  // 1. Budgets
  step('budgets');
  await page.goto(base + '/budgets');
  await page.fill('#budget-total', '15000');
  await page.fill('#budget-google_ads', '6000');
  await page.fill('#budget-meta', '3500');
  await page.fill('#budget-linkedin', '1500');
  await page.click('button:has-text("Save budgets")');
  await page.waitForSelector('.banner.success');
  const meters = await page.locator('.meter-row').count();
  assert(meters === 4, 'expected 4 pacing rows, got ' + meters);
  await page.screenshot({ path: out + '/e2e-budgets.png', fullPage: true });

  // 2. Campaigns: pause + budget edit
  step('campaign pause');
  await page.goto(base + '/campaigns');
  const firstRow = page.locator('#campaign-table tbody tr[data-key]').first();
  const name = (await firstRow.locator('.name').innerText()).split('\n')[0];
  await firstRow.locator('.toggle-status').click();
  await page.waitForFunction(() => document.querySelector('#campaign-table tbody tr[data-key]').dataset.status === 'PAUSED');
  assert((await firstRow.locator('.toggle-status').innerText()).trim() === 'Enable', 'button should flip to Enable');
  step('campaign budget edit');
  const row2 = page.locator('#campaign-table tbody tr[data-key]').nth(1);
  await row2.locator('.edit-budget').click();
  await row2.locator('.budget-edit input').fill('60.50');
  await row2.locator('.budget-edit button:has-text("Save")').click();
  await page.waitForFunction(() => { const el = document.querySelectorAll('#campaign-table tbody tr[data-key]')[1].querySelector('.budget-text'); return el && el.textContent.includes('60.50'); });
  step('campaign filters');
  await page.selectOption('#c-platform', 'pinterest');
  const visible = await page.locator('#campaign-table tbody tr[data-key]:not([hidden])').count();
  assert(visible === 2, 'pinterest filter should show 2 rows, got ' + visible);
  await page.selectOption('#c-platform', '');
  await page.reload();
  const statusAfterReload = await page.locator(`#campaign-table tbody tr[data-key]`).evaluateAll((rows, n) => rows.find(r => r.querySelector('.name').firstChild.textContent.trim() === n).dataset.status, name);
  assert(statusAfterReload === 'PAUSED', 'pause should persist across reloads');
  await page.screenshot({ path: out + '/e2e-campaigns.png' });

  // 3. Publish now
  step('publish now');
  await page.goto(base + '/publish');
  await page.check('input[data-network="facebook"]');
  await page.check('input[data-network="x"]');
  await page.check('input[data-network="instagram"]');
  await page.fill('#body', 'Fall sale: 20% off business cards this week only. Free proof with every order! #printing #smallbusiness');
  await page.fill('#link', 'https://priorityprintservice.com/business-cards');
  await page.fill('#utm_campaign', 'Fall Business Cards');
  assert(!(await page.isHidden('#needs-image')), 'image warning should show for Instagram without an image');
  await page.fill('#image_url', 'https://priorityprintservice.com/wp-content/uploads/cards.jpg');
  await page.dispatchEvent('#image_url', 'input');
  assert(await page.isHidden('#needs-image'), 'image warning should hide once an image is set');
  assert(!(await page.isHidden('#x-notice')), 'X billing notice should show');
  const counters = await page.innerText('#counters');
  assert(/X \d+ \/ 280/.test(counters), 'X counter missing: ' + counters);
  await page.screenshot({ path: out + '/e2e-compose.png', fullPage: true });
  await page.click('#btn-now');
  await page.waitForSelector('.banner.success');
  const flash = await page.innerText('.banner.success');
  assert(flash.includes('Published to 3'), 'publish flash: ' + flash);

  step('history');
  await page.goto(base + '/publish?tab=history');
  const links = await page.locator('.post-item a[target=_blank]').count();
  assert(links === 3, 'history should link 3 published posts, got ' + links);
  const hrefs = await page.locator('.post-item a[target=_blank]').evaluateAll(as => as.map(a => a.href));
  console.log('   links:', hrefs.join(' | '));

  // 4. Validation: Pinterest without image is refused
  step('validation');
  await page.goto(base + '/publish');
  await page.check('input[data-network="pinterest"] >> nth=0');
  await page.fill('#body', 'Pin me');
  await page.click('#btn-now');
  await page.waitForSelector('.banner.error');
  assert((await page.innerText('.banner.error')).includes('Pinterest needs an image'), 'pinterest image validation');

  // 5. Schedule
  step('schedule');
  await page.goto(base + '/publish');
  await page.check('input[data-network="linkedin"]');
  await page.fill('#body', 'We print event programs, badges and signage for conferences. Ask us for a bulk quote.');
  const tomorrow = new Date(Date.now() + 26 * 3600 * 1000);
  const local = new Date(tomorrow.getTime() - tomorrow.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  await page.fill('#schedule-local', local);
  await page.click('#btn-schedule');
  await page.waitForSelector('.banner.success');
  const queued = await page.locator('.post-item').count();
  assert(queued === 1, 'queue should have 1 post, got ' + queued);
  await page.goto(base + '/publish?tab=calendar');
  const chips = await page.locator('#calendar .ev').count();
  assert(chips >= 1, 'calendar should show posts, got ' + chips);
  await page.screenshot({ path: out + '/e2e-calendar.png', fullPage: true });

  // 6. Automation: template -> save -> dry run
  step('automation');
  await page.goto(base + '/automation?template=2');
  await page.click('button:has-text("Save rule")');
  await page.waitForSelector('.banner.success');
  await page.goto(base + '/automation?template=1');
  await page.fill('#r-minspend', '1');
  await page.selectOption('#r-op', '<');
  await page.fill('#r-threshold', '5');
  await page.click('button:has-text("Save rule")');
  await page.waitForSelector('.banner.success');
  await page.click('button:has-text("Preview all (dry run)")');
  await page.waitForSelector('#outcomes .banner');
  const outcomeText = await page.innerText('#outcomes');
  console.log('   ' + outcomeText.split('\n')[0]);
  await page.screenshot({ path: out + '/e2e-automation.png', fullPage: true });

  // 7. UTM
  step('utm');
  await page.goto(base + '/utm');
  await page.fill('#u-url', 'https://priorityprintservice.com/brochures?ref=home');
  await page.click('button.preset >> nth=1');
  await page.fill('#u-campaign', 'Spring Brochures 2027');
  await page.dispatchEvent('#u-campaign', 'blur');
  const tagged = await page.innerText('#u-result');
  assert(tagged.includes('utm_source=facebook') && tagged.includes('utm_campaign=spring-brochures-2027') && tagged.includes('ref=home'), 'utm: ' + tagged);
  await page.click('button:has-text("Save link")');
  await page.waitForSelector('.banner.success');

  // 8. Dashboard pacing + activity
  step('dashboard + activity');
  await page.goto(base + '/');
  assert(await page.locator('.meter').count() === 4, 'dashboard pacing meters');
  await page.hover('#spend-chart svg rect[tabindex="0"] >> nth=10');
  assert(await page.isVisible('.tooltip'), 'chart tooltip on hover');
  await page.screenshot({ path: out + '/e2e-dashboard.png', fullPage: true });
  await page.goto(base + '/activity');
  const acts = await page.locator('.activity-item').count();
  console.log('   activity entries:', acts);
  assert(acts >= 6, 'activity log should have entries');
  await page.screenshot({ path: out + '/e2e-activity.png', fullPage: true });

  // 9. CSRF: a forged POST without the token is rejected
  step('csrf');
  const forged = await page.evaluate(async () => (await fetch('/api/campaigns/status', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })).status);
  assert(forged === 400, 'forged POST should be 400, got ' + forged);

  await browser.close();
  console.log(errors.length ? 'ERRORS:\n' + errors.join('\n') : 'E2E OK, no page errors');
})().catch(e => { console.error(e.message); process.exit(1); });
