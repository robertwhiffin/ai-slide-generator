// Tiny chromium-launch probe. Reports whether chromium can launch on this
// host with our standard launch options. Used to de-risk Databricks Apps
// deploys: if this exits 0 with PROBE_OK, the sidecar's full pipeline can
// rely on chromium working.
import { chromium } from 'playwright';

const launchOptions = {
  headless: true,
  channel: 'chromium',
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
};

async function main() {
  console.error('[probe] launching chromium...');
  const browser = await chromium.launch(launchOptions);
  console.error('[probe] launched OK, opening page...');
  const ctx = await browser.newContext({ viewport: { width: 100, height: 100 } });
  const page = await ctx.newPage();
  await page.setContent('<h1>probe</h1>');
  await browser.close();
  console.log('PROBE_OK');
}

main().catch((err) => {
  console.error('[probe] FAIL:', err.stack || err);
  process.exit(1);
});
