import { test, expect } from '@playwright/test';

const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64');

test('PhotoCraft real project: import, place, drag, resize, clear, undo, close and reopen', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/photocraft/warm', (route) => route.fulfill({ json: { warming: false } }));
  await page.goto('/#photocraft');
  await expect(page.getByRole('heading', { name: 'PhotoCraft projects' })).toBeVisible();
  const projectName = `Browser project lifecycle ${Date.now()}`;
  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByLabel('Project name').fill(projectName);
  await page.getByLabel('Width (px)').fill('400');
  await page.getByLabel('Height (px)').fill('300');
  await page.getByRole('button', { name: 'Create project' }).click();
  await expect(page.getByRole('button', { name: 'Clear canvas', exact: true })).toBeEnabled();
  const save = page.getByRole('link', { name: 'Save project file', exact: true });
  const match = (await save.getAttribute('href'))!.match(/workspaces\/([a-f0-9]+)\//)!;
  const id = match[1];
  async function document() { return (await request.get(`/api/photocraft/workspaces/${id}`)).json(); }
  const before = await document();
  await page.getByLabel('Import project images', { exact: true }).setInputFiles([
    { name: 'logo.png', mimeType: 'image/png', buffer: PNG },
    { name: 'second-source.png', mimeType: 'image/png', buffer: PNG },
  ]);
  await expect(page.getByLabel('Place logo.png', { exact: true })).toBeEnabled();
  const imported = await document();
  expect(imported.revision).toBe(before.revision);
  expect(imported.state.layers).toHaveLength(1);
  expect(imported.assets).toHaveLength(2);
  await page.getByLabel('Place logo.png', { exact: true }).selectOption('original');
  await expect.poll(async () => (await document()).state.layers.length).toBe(2);
  // Enlarge the one-pixel fixture through the real engine so moving/corner gestures are practical.
  const placed = await document();
  const job = await (await request.post(`/api/photocraft/workspaces/${id}/operation`, { data: {
    revision: placed.revision, commands: [{ command: 'edit.transform', params: { layer: placed.state.layers[0].id, scaleX: 8000, scaleY: 6000 } }],
  } })).json();
  await expect.poll(async () => (await (await request.get(`/api/jobs/${job.id}`)).json()).state).toBe('done');
  await page.getByRole('button', { name: 'Close project', exact: true }).click();
  await page.getByRole('button', { name: new RegExp(projectName) }).click();
  const frame = page.locator('.pc-frame');
  await expect(frame).toBeVisible();
  const bounds = (await frame.boundingBox())!;
  const resized = await document();
  const originalBounds = resized.state.layers[0].bounds;
  const startX = bounds.x + (originalBounds[0] + originalBounds[2] / 2) * bounds.width / 400;
  const startY = bounds.y + (originalBounds[1] + originalBounds[3] / 2) * bounds.height / 300;
  await page.mouse.move(startX, startY); await page.mouse.down();
  await page.mouse.move(startX + bounds.width / 10, startY + bounds.height / 10, { steps: 6 });
  await page.mouse.up();
  await expect.poll(async () => (await document()).state.layers[0].bounds[0]).toBeCloseTo(originalBounds[0] + 40, 0);
  await expect(page.getByLabel('Resize image corner 3')).toBeEnabled();
  const corner = (await page.getByLabel('Resize image corner 3').boundingBox())!;
  await page.mouse.move(corner.x + 5, corner.y + 5); await page.mouse.down();
  await page.mouse.move(corner.x + 35, corner.y + 25, { steps: 5 }); await page.mouse.up();
  await expect.poll(async () => (await document()).state.layers[0].bounds[2]).toBeGreaterThan(originalBounds[2]);
  const changed = await document();
  await page.getByRole('button', { name: 'Clear canvas', exact: true }).click();
  await expect.poll(async () => (await document()).state.layers.length).toBe(1);
  expect((await document()).assets).toHaveLength(2);
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect.poll(async () => (await document()).revision).toBe(changed.revision);
  const download = page.waitForEvent('download');
  await save.click();
  expect((await download).suggestedFilename()).toMatch(/\.istudio$/);
  await page.screenshot({ path: '../build/project-browser-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => window.document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: '../build/project-browser-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'Close project', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'PhotoCraft projects' })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: new RegExp(projectName) }).click();
  await expect(page.getByLabel('Place logo.png', { exact: true })).toBeVisible();
  expect((await document()).revision).toBe(changed.revision);
  expect(errors).toEqual([]);
});

test('Krita project UI keeps uploads in its bin and sends explicit lifecycle and layer actions', async ({ page }) => {
  const calls: string[] = [];
  const id = 'c'.repeat(32), layer = '11111111-1111-1111-1111-111111111111';
  let opened = false;
  let project: any = { id, name: 'Krita project UI', width: 400, height: 300, assets: [], updated: 1 };
  const doc = { name: 'project.kra', width: 400, height: 300, modified: false, activeLayer: layer,
    layers: [{ id: layer, name: 'Image layer', depth: 0, kind: 'Pixel', visible: true, active: true, bounds: [80, 70, 100, 80] }] };
  await page.route('**/api/krita', (route) => route.fulfill({ json: { connected: true, state: opened ? doc : null,
    project: opened ? project : null, capabilities: { projects: true }, preview: false, preview_version: 1, events: [] } }));
  await page.route('**/api/krita/projects**', async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (request.method() === 'GET') return route.fulfill({ json: { projects: [project] } });
    calls.push(path);
    if (path.endsWith('/assets')) project = { ...project, assets: [{ id: 'd'.repeat(32), name: 'logo.png', width: 1, height: 1, thumbnail: '/fixture.png' }] };
    const action = request.headers()['content-type']?.includes('json') ? request.postDataJSON()?.action : undefined;
    opened = action !== 'close';
    if (action === 'clear') project.can_restore = true;
    return route.fulfill({ json: { project, closed: action === 'close', message: 'Project saved.' } });
  });
  await page.route('**/fixture.png', (route) => route.fulfill({ contentType: 'image/png', body: PNG }));
  await page.goto('/#krita');
  await expect(page.getByRole('heading', { name: 'Krita projects' })).toBeVisible();
  await page.getByRole('button', { name: /Krita project UI/ }).click();
  await expect(page.getByRole('button', { name: 'Import project images', exact: true })).toBeEnabled();
  await page.getByLabel('Import Krita project images').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: PNG });
  await expect(page.getByLabel('Place logo.png', { exact: true })).toBeVisible();
  expect(calls.filter((path) => path.endsWith('/place'))).toHaveLength(0);
  await page.getByLabel('Place logo.png', { exact: true }).selectOption('original');
  await expect.poll(() => calls.filter((path) => path.endsWith('/place')).length).toBe(1);
  await page.getByRole('button', { name: 'Hide Image layer' }).click();
  await expect.poll(() => calls.filter((path) => path.includes('/layers/')).length).toBe(1);
  await page.getByRole('button', { name: 'Clear canvas', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Restore previous canvas' })).toBeVisible();
  await page.getByRole('button', { name: 'Close project', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Krita projects' })).toBeVisible();
  await page.screenshot({ path: '../build/krita-project-home.png', fullPage: true });
});
