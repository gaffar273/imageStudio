import { test, expect, type Page } from '@playwright/test';

const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=',
  'base64',
);
const ID = 'a'.repeat(32);

function documentAt(revision: string, extra: object = {}) {
  return {
    id: ID,
    name: 'harbour.png',
    revision,
    preview: `/api/photocraft/workspaces/${ID}/preview/${revision}`,
    original: `/api/photocraft/workspaces/${ID}/preview/${'b'.repeat(32)}`,
    cursor: revision === 'b'.repeat(32) ? 0 : 1,
    history: [
      { id: 'b'.repeat(32), label: 'Original', created: 1 },
      ...(revision === 'b'.repeat(32)
        ? []
        : [
            {
              id: revision,
              label: 'Warm the sky',
              created: 2,
              requirements: ['Warm the sky a little', 'add “SUMMER” at the top'],
              checks: [{ requirement: 1, check: 'Text reads exactly “SUMMER”', passed: true }],
              review: [{ requirement: 0, item: 'Warm the sky a little', verdict: 'done', note: 'The sky is warmer.' }],
            },
          ]),
    ],
    can_undo: revision !== 'b'.repeat(32),
    can_redo: false,
    state: {
      width: 1200,
      height: 800,
      mode: 'Rgb',
      depth: 8,
      activeLayer: 2,
      hasSelection: false,
      layers: [
        { id: 3, name: 'SUMMER', kind: 'Type', visible: true, opacity: 1, selected: false, text: { text: 'SUMMER', font: 'Inter', sizePt: 64 } },
        { id: 2, name: 'Photo', kind: 'Smart Object', visible: true, opacity: 1, selected: true, smartFilters: [{ command: 'filter.cameraRaw', params: {}, visible: true }] },
      ],
    },
    ...extra,
  };
}

async function mockStudio(page: Page) {
  const calls: { path: string; body: any }[] = [];
  let job: any = {};
  await page.route('**/api/photocraft/capabilities', (route) =>
    route.fulfill({
      json: {
        installed: true,
        brain: true,
        discovered: 3,
        runnable: 2,
        note: '',
        commands: [
          { id: 'filter.blur.gaussianBlur', label: 'Gaussian Blur…', params: '{"radius":0.1..1000=1}', category: 'filter.blur', runnable: true, reason: '', menu: ['Filter', 'Blur'], fields: [{ name: 'radius', type: 'number', min: 0.1, max: 1000, default: 1 }] },
          { id: 'layer.newAdjustmentLayer.curves', label: 'Curves…', params: '{}', category: 'layer.newAdjustmentLayer', runnable: true, reason: '', menu: ['Layer'], fields: [] },
          { id: 'file.print', label: 'Print…', params: '{}', category: 'file.print', runnable: false, reason: 'Use the desktop app.', menu: ['File'], fields: [] },
        ],
      },
    }),
  );
  await page.route('**/api/photocraft/fonts', (route) => route.fulfill({ json: { fonts: ['Georgia', 'Inter'] } }));
  await page.route('**/api/photocraft/workspaces', (route) => route.fulfill({ json: { workspaces: [{ id: ID, name: 'harbour.png', updated: 1 }] } }));
  await page.route(`**/api/photocraft/workspaces/${ID}`, (route) => route.fulfill({ json: documentAt('b'.repeat(32)) }));
  await page.route('**/preview/**', (route) => route.fulfill({ contentType: 'image/png', body: PNG }));
  await page.route('**/api/jobs/craft-job', (route) => route.fulfill({ json: job }));
  await page.route(`**/api/photocraft/workspaces/${ID}/**`, async (route) => {
    const url = route.request().url();
    if (url.includes('/preview/')) return route.fallback();
    const body = route.request().postDataJSON();
    calls.push({ path: new URL(url).pathname, body });
    if (url.endsWith('/plan')) {
      job = {
        id: 'craft-job',
        state: 'done',
        progress: 1,
        message: 'Your edit plan is ready.',
        plan: {
          id: 'c'.repeat(32),
          revision: 'b'.repeat(32),
          prompt: body.prompt,
          summary: body.prompt,
          requirements: ['Warm the sky a little', 'add “SUMMER” at the top'],
          edits: [
            { action: 'temperature', quote: 'Warm the sky a little', target: 'sky', strength: 'subtle', value: null, explain: 'Select the sky → More temperature' },
            { action: 'add_text', quote: 'add “SUMMER” at the top', target: 'whole image', text: 'SUMMER', position: 'top', value: null, explain: 'Add “SUMMER” · 64 pt, top' },
          ],
          preserve: ['Keep the boats unchanged'],
          questions: [],
          notes: [],
          unresolved: [],
          regions: [{ requirement: 0, label: 'sky', boxes: [[0, 0, 1, 0.4]] }],
          planner: 'Qwen3.5 vision',
          steps: [{ command: 'select.sky', label: 'Select the sky', params: {}, requirements: [0] }],
        },
      };
    } else {
      job = { id: 'craft-job', state: 'done', progress: 1, message: 'Document updated.', workspace: documentAt('d'.repeat(32)) };
    }
    await route.fulfill({ status: 202, json: { ...job, state: 'running' } });
  });
  return calls;
}

test('PhotoCraft studio: plan, review, apply, tool panels and layout', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const calls = await mockStudio(page);
  await page.goto('/');
  await page.evaluate((id) => {
    localStorage.setItem('studio:photocraft-workspace', id);
    localStorage.setItem('studio:photocraft-tool', 'assistant');
    localStorage.removeItem('studio:photocraft-job');
  }, ID);
  await page.goto('/#photocraft');
  await expect(page.getByText('harbour.png').first()).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'PhotoCraft tools' }).getByRole('button')).toHaveCount(8);

  await page.getByLabel('PhotoCraft instructions').fill('Warm the sky a little and add “SUMMER” at the top. Keep the boats unchanged.');
  await page.getByRole('button', { name: 'Plan', exact: true }).click();
  await expect(page.getByText('I UNDERSTOOD 2 CHANGES')).toBeVisible();
  await expect(page.locator('.pc-preserve').getByText('Keep the boats unchanged')).toBeVisible();
  await expect(page.locator('.pc-region')).toHaveCount(1);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: '../docs/screenshots/photocraft-studio-plan.png' });
  await page.getByRole('button', { name: 'Apply 2 changes' }).click();
  await expect(page.getByText('RESULT CHECK')).toBeVisible();
  await expect(page.getByText('Text reads exactly “SUMMER”')).toBeVisible();
  expect(calls.find((call) => call.path.endsWith('/operation'))?.body).toMatchObject({ plan_id: 'c'.repeat(32), partial: false });

  await page.getByRole('button', { name: 'Adjust' }).click();
  await page.getByLabel('Apply to').getByRole('radio', { name: 'Sky' }).click();
  await page.locator('.pc-slider', { hasText: 'Temperature' }).locator('input').fill('30');
  await page.getByRole('button', { name: 'Apply 1 adjustment' }).click();
  const adjust = calls.filter((call) => call.path.endsWith('/edits')).at(-1)!.body;
  expect(adjust.edits).toEqual([expect.objectContaining({ action: 'temperature', value: 30, direction: 'increase', target: 'sky' })]);

  await page.getByRole('button', { name: 'Text', exact: true }).click();
  await page.getByLabel('Words').fill('Hello');
  await page.getByRole('radio', { name: 'top left' }).click();
  await page.getByRole('button', { name: 'Add text' }).click();
  const text = calls.filter((call) => call.path.endsWith('/edits')).at(-1)!.body;
  expect(text.edits[0]).toMatchObject({ action: 'add_text', text: 'Hello', position: 'top left' });

  await page.getByRole('button', { name: 'Filters' }).click();
  await page.getByRole('button', { name: 'Apply as a smart filter' }).click();
  const filter = calls.filter((call) => call.path.endsWith('/operation')).at(-1)!.body;
  expect(filter.commands.map((c: { command: string }) => c.command)).toEqual(['studio.select_photo', 'filter.blur.gaussianBlur']);

  await page.getByRole('tab', { name: 'History' }).click();
  await page.getByRole('button', { name: /Original/ }).click();
  expect(calls.filter((call) => call.path.endsWith('/operation')).at(-1)!.body).toMatchObject({ action: 'goto', index: 0 });

  await page.getByRole('button', { name: 'Adjust' }).click();
  await page.screenshot({ path: '../docs/screenshots/photocraft-studio-desktop.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: '../docs/screenshots/photocraft-studio-mobile.png', fullPage: true });
  expect(errors).toEqual([]);
});
