import { test, expect } from '@playwright/test';

test('desktop studio, navigation, favorites, saved settings and edit handoff', async ({ page }) => {
  // Keep preferences isolated and use a generated image for the reuse-settings check.
  let favorites: string[] = [];
  await page.route('**/api/favorites', async (route) => {
    if (route.request().method() === 'POST') {
      const { name, favorite } = route.request().postDataJSON();
      favorites = favorites.filter((value) => value !== name);
      if (favorite) favorites.push(name);
    }
    await route.fulfill({ json: { names: favorites } });
  });
  await page.route('**/api/library', async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.images = data.images.filter((image: { metadata: { mode?: string } }) =>
      !['edit', 'krita'].includes(image.metadata.mode || ''));
    data.total = data.images.length;
    await route.fulfill({ json: data });
  });
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Generate image', exact: false })).toBeVisible();
  await expect(page.locator('.image-card').first()).toBeVisible();
  await page.screenshot({ path: '../docs/screenshots/react-studio-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'Surprise me' }).click();
  await expect(page.getByRole('textbox', { name: 'Image prompt' })).not.toBeEmpty();
  await expect(page.getByRole('button', { name: 'Generate image', exact: false })).toBeEnabled();
  await page.getByRole('button', { name: 'My library', exact: true }).click();
  await expect(page.locator('.library-grid .image-card').first()).toBeVisible();
  const count = await page.locator('.library-grid .image-card').count();
  expect(count).toBeGreaterThan(4);
  await page.locator('.library-grid .image-card').first().hover();
  await page.locator('.library-grid .favorite-button').first().click();
  await page.getByRole('button', { name: /Favorites/ }).click();
  await expect(page.locator('.library-grid .image-card')).toHaveCount(1);
  await page.locator('.image-card-open').first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Download original' })).toHaveAttribute('href', /download$/);
  await page.getByRole('button', { name: 'Reuse settings', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Image prompt' })).not.toBeEmpty();
  await page.getByRole('button', { name: 'My library', exact: true }).click();
  await page.locator('.image-card-open').first().click();
  await page.getByRole('button', { name: 'Edit image', exact: true }).last().click();
  await expect(page.getByAltText('Image to edit')).toBeVisible();
  await page.getByRole('combobox', { name: 'Editing tool' }).selectOption('kontext');
  await page.getByRole('switch', { name: /Paint an area/ }).check();
  await expect(page.locator('canvas')).toHaveClass('painting');
  await page.getByRole('textbox', { name: 'Edit instruction' }).fill('Warm the lighting');
  await expect(page.getByRole('button', { name: 'Apply edit' })).toBeEnabled();
  await page.getByRole('button', { name: 'Studio settings', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Generation models' })).toBeVisible();
  await page.getByRole('button', { name: 'Krita canvas', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open Krita', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'How to use Image Studio' }).click();
  await expect(page.getByRole('dialog', { name: 'Getting started' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Getting started' })).not.toBeVisible();
  expect(errors).toEqual([]);
});

test('mobile layout has no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.locator('.prompt-panel')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: '../docs/screenshots/react-studio-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'My library', exact: true }).click();
  await expect(page.locator('.library-grid')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test('browser shows render progress, cancellation, and server errors', async ({ page }) => {
  await page.route('**/api/generate', (route) =>
    route.fulfill({
      status: 202,
      json: { id: 'browser-test', state: 'running', progress: 0, message: 'Preparing image', images: [] },
    }),
  );
  let stopped = false;
  await page.route('**/api/jobs/browser-test', (route) =>
    route.fulfill({
      json: {
        id: 'browser-test',
        state: stopped ? 'cancelled' : 'running',
        progress: 0.4,
        message: stopped ? 'Generation stopped.' : 'Rendering 2 of 4',
        images: [],
      },
    }),
  );
  await page.route('**/api/jobs/browser-test/cancel', (route) => {
    stopped = true;
    return route.fulfill({ json: { state: 'cancelled' } });
  });
  await page.goto('/');
  await page.getByRole('textbox', { name: 'Image prompt' }).fill('A small cabin');
  await page.getByRole('button', { name: /Generate image/ }).click();
  await expect(page.getByText('Rendering 2 of 4')).toBeVisible();
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(page.locator('.job-status')).toContainText('Generation stopped.');
  await page.route('**/api/generate', (route) =>
    route.fulfill({ status: 409, json: { detail: 'The studio is already rendering.' } }),
  );
  await page.getByRole('button', { name: /Generate image/ }).click();
  await expect(page.getByRole('alert')).toContainText('The studio is already rendering.');
});

test('Krita upload, library handoff, instructions and connection states', async ({ page }) => {
  const commands: Record<string, string>[] = [];
  let connected = true;
  let document: object | null = {
    name: 'Untitled',
    width: 1024,
    height: 1024,
    layers: [{ name: 'Background', active: true, visible: true, depth: 0 }],
  };
  await page.route('**/api/krita', async (route) => {
    if (route.request().method() === 'POST') {
      commands.push(route.request().postDataJSON());
      return route.fulfill({ json: { message: 'Sent to Krita.' } });
    }
    return route.fulfill({
      json: { connected, state: document, preview: false, preview_version: 0, events: [] },
    });
  });
  await page.goto('/#krita');
  await expect(page.getByRole('heading', { name: 'Untitled', exact: true })).toBeVisible();
  await expect(page.getByText('Running locally', { exact: true })).toHaveCount(0);
  await page.getByLabel('Upload image to Krita').setInputFiles({
    name: 'test.png',
    mimeType: 'image/png',
    buffer: Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j7ioAAAAASUVORK5CYII=',
      'base64',
    ),
  });
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0].action).toBe('import');
  expect(commands[0].image).toMatch(/^data:image\/png;base64,/);
  await page.getByRole('button', { name: 'From library', exact: true }).click();
  await expect(page.locator('.krita-library-picker')).toBeVisible();
  await page.getByRole('textbox', { name: 'Search library images' }).fill('zz-no-matching-images-zz');
  await expect(page.getByText('No images match your search.')).toBeVisible();
  await page.getByRole('textbox', { name: 'Search library images' }).fill('');
  await page.locator('.krita-picker-grid button').first().click();
  await expect(page.locator('.krita-library-picker')).not.toBeVisible();
  expect(commands[1].action).toBe('open');
  expect(commands[1].image).toMatch(/\.png$/);
  await page.getByRole('textbox', { name: 'Krita instruction' }).fill('Warm the lighting');
  await page.getByRole('textbox', { name: 'Krita instruction' }).press('Control+Enter');
  await expect.poll(() => commands.length).toBe(3);
  expect(commands[2]).toMatchObject({ action: 'prompt', text: 'Warm the lighting' });
  await expect(page.getByRole('textbox', { name: 'Krita instruction' })).toBeEmpty();
  await page.screenshot({ path: '../docs/screenshots/krita-workspace-desktop.png', fullPage: true });
  document = null;
  await expect(page.getByRole('heading', { name: 'Start with an image' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save to library', exact: true })).toBeDisabled();
  connected = false;
  await expect(page.getByText('Open Krita to connect', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /New blank canvas/ })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Upload image', exact: true }).first()).toBeEnabled();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: '../docs/screenshots/krita-workspace-mobile.png', fullPage: true });
});
