/**
 * "What's new in Tellr" popup, end to end against the real bundled notes.
 *
 * The whole file skips until a release bumps in a notes file with at least one
 * item (frontend/src/whatsNew/releases/<version>.json); its first real run is on
 * a release bump PR.  Nothing here is hard-coded to a version: the newest notes
 * file with items is read from disk, so the spec keeps passing as releases land.
 *
 * Every describe but the last sets its own storageState.  The suite-wide one (playwright.config.ts)
 * marks the tour completed AND every release seen, which would hide the popup.
 *
 * Pins Review Focus 4: a brand-new user who finishes the welcome guide never gets
 * the popup, in that session or on the next load.
 */
import { readdirSync, readFileSync } from 'node:fs';
import type { Locator, Page } from '@playwright/test';
import { test, expect } from '../fixtures/base-test';
import { setupMocks } from '../helpers/setup-mocks';
import { hasReleaseNotesWithItems, newestReleaseNotesVersion } from '../helpers/whats-new';
import {
  WHATS_NEW_STORAGE_KEY,
  compareVersions,
  isReleaseVersion,
  type ReleaseNotes,
} from '../../src/whatsNew/releaseNotes';

test.skip(!hasReleaseNotesWithItems(), 'no release notes bundled yet; first real run is on a release bump PR');

// ── the bundled notes, read from disk ─────────────────────────────────────────

const RELEASES_DIR = new URL('../../src/whatsNew/releases/', import.meta.url);

/** Every `<X.Y.Z>.json` notes file, newest first.  Empty when none are bundled. */
function bundledReleases(): ReleaseNotes[] {
  return readdirSync(RELEASES_DIR)
    .filter((f) => f.endsWith('.json'))
    .map((f) => f.slice(0, -'.json'.length))
    .filter(isReleaseVersion) // compareVersions is only safe on X.Y.Z
    .map((stem) => JSON.parse(readFileSync(new URL(`${stem}.json`, RELEASES_DIR), 'utf8')) as ReleaseNotes)
    .sort((a, b) => compareVersions(b.version, a.version));
}

const RELEASES = bundledReleases();
/** The popup shows only releases with items; its first section is this one. */
const NEWEST_WITH_ITEMS = RELEASES.find((r) => r.items.length > 0) ?? null;
/** Dismissing records the newest release over ALL files, empty ones included. */
const NEWEST_OVERALL = RELEASES[0]?.version ?? null;

function newest(): ReleaseNotes {
  if (NEWEST_WITH_ITEMS === null) throw new Error('no notes file with items (the skip should have fired)');
  return NEWEST_WITH_ITEMS;
}

// ── locators ──────────────────────────────────────────────────────────────────

const ORIGIN = 'http://localhost:3000';
const TOUR_DONE = { name: 'tellr-app-tour-completed', value: 'true' };

/** Longer than the 800 ms auto-open delay, with headroom for a slow CI machine. */
const PAST_AUTO_OPEN_MS = 1500;

const whatsNew = (page: Page) => page.getByRole('dialog', { name: "What's new in Tellr", exact: true });
const welcome = (page: Page) => page.getByRole('dialog', { name: 'Welcome to Tellr', exact: true });
const sidebarWhatsNew = (page: Page) => page.getByRole('button', { name: "What's new", exact: true });
const releaseSection = (page: Page, version: string) =>
  whatsNew(page).getByRole('region', { name: `Tellr ${version}`, exact: true });
const newBadge = (scope: Locator) => scope.getByText('New', { exact: true });

const lastSeen = (page: Page) =>
  page.evaluate((key) => localStorage.getItem(key), WHATS_NEW_STORAGE_KEY);

/**
 * The app has mounted: the sidebar entry renders from the same provider that
 * schedules the auto-open timer, so the timer is running once this is visible.
 * Anchoring the fixed wait here keeps a slow page load from passing a negative
 * assertion before the timer had a chance to fire.
 */
async function waitPastAutoOpen(page: Page) {
  await expect(sidebarWhatsNew(page)).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(PAST_AUTO_OPEN_MS);
}

test.beforeEach(async ({ page }) => {
  await setupMocks(page);
});

// ── an existing user, upgraded onto a release with notes ──────────────────────

test.describe("What's new: an existing user after an upgrade", () => {
  // Only the tour flag: this user has used Tellr before but has seen no notes.
  test.use({
    storageState: { cookies: [], origins: [{ origin: ORIGIN, localStorage: [TOUR_DONE] }] },
  });

  test('opens after an upgrade, with the newest release marked New', async ({ page }) => {
    const notes = newest();
    await page.goto('/');

    await expect(whatsNew(page)).toBeVisible({ timeout: 10_000 });
    const section = releaseSection(page, notes.version);
    await expect(section).toBeVisible();
    await expect(newBadge(section)).toBeVisible();
    await expect(section).toContainText(notes.items[0].title);
    // An existing user never sees the welcome guide on top of it.
    await expect(welcome(page)).toHaveCount(0);
  });

  test('dismissal survives a reload', async ({ page }) => {
    await page.goto('/');
    await expect(whatsNew(page)).toBeVisible({ timeout: 10_000 });

    await whatsNew(page).getByRole('button', { name: 'Got it', exact: true }).click();
    await expect(whatsNew(page)).toHaveCount(0);
    await expect.poll(() => lastSeen(page)).toBe(NEWEST_OVERALL);

    await page.reload();
    await waitPastAutoOpen(page);
    await expect(whatsNew(page)).toHaveCount(0);
  });

  test('reopens from the sidebar with no New badge', async ({ page }) => {
    const notes = newest();
    await page.goto('/');
    await expect(whatsNew(page)).toBeVisible({ timeout: 10_000 });
    await whatsNew(page).getByRole('button', { name: 'Got it', exact: true }).click();
    await expect(whatsNew(page)).toHaveCount(0);

    await sidebarWhatsNew(page).click();

    await expect(whatsNew(page)).toBeVisible();
    // The notes are still there; only the badge is gone.
    await expect(releaseSection(page, notes.version)).toContainText(notes.items[0].title);
    await expect(newBadge(whatsNew(page))).toHaveCount(0);
  });
});

// ── a brand-new user (Review Focus 4) ─────────────────────────────────────────

test.describe("What's new: a brand-new user", () => {
  // Nothing in localStorage at all: no tour flag, no last-seen release.
  test.use({ storageState: { cookies: [], origins: [] } });

  test('gets the welcome guide, never the popup, this load or the next', async ({ page }) => {
    await page.goto('/');

    await expect(welcome(page)).toBeVisible({ timeout: 10_000 });
    // The sidebar entry is hidden while the welcome guide is up, so wait on the clock instead.
    await page.waitForTimeout(PAST_AUTO_OPEN_MS);
    await expect(whatsNew(page)).toHaveCount(0);
    await expect(welcome(page)).toBeVisible();

    await welcome(page).getByRole('button', { name: 'Get Started', exact: true }).click();
    await expect(welcome(page)).toHaveCount(0);
    // Finishing the welcome guide counts as having seen every release.
    await expect.poll(() => lastSeen(page)).toBe(NEWEST_OVERALL);

    // Not later in this session...
    await waitPastAutoOpen(page);
    await expect(whatsNew(page)).toHaveCount(0);

    // ...and not on the next load either.
    await page.reload();
    await waitPastAutoOpen(page);
    await expect(whatsNew(page)).toHaveCount(0);
    await expect(welcome(page)).toHaveCount(0);
  });
});

// ── the suite-wide storageState ───────────────────────────────────────────────

test.describe("What's new: the suite-wide storageState", () => {
  // No test.use here: this runs under the global storageState from playwright.config.ts.
  // Every other E2E spec relies on it marking all bundled releases as seen, so the popup
  // never covers their pages.  This pins that seeding.
  test('marks every bundled release as seen, so the popup never opens', async ({ page }) => {
    await page.goto('/');

    await expect.poll(() => lastSeen(page)).toBe(newestReleaseNotesVersion());
    await waitPastAutoOpen(page);
    await expect(whatsNew(page)).toHaveCount(0);
  });
});
