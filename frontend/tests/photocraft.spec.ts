import { test, expect } from '@playwright/test';

test('PhotoCraft presets, submission, exports and AI mask controls', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  let job: object;
  await page.route('**/api/jobs/photocraft-ui-check', (route) => route.fulfill({ json: job }));
  await page.route('**/api/edit', async (route) => {
    const body = route.request().postDataJSON();
    expect(body.engine).toBe('photocraft');
    expect(body.prompt).toBe('Professional polish');
    expect(body.mask).toBeNull();
    job = {
      id: 'photocraft-ui-check',
      state: 'done',
      progress: 1,
      message: 'PhotoCraft edit ready.',
      images: [
        {
          name: 'photocraft_ui.png',
          url: body.image,
          thumbnail: body.image,
          created: 1,
          metadata: { model: 'PhotoCraft', layered_document: 'photocraft_ui.psd' },
        },
      ],
    };
    await route.fulfill({ status: 202, json: job });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Edit image', exact: true }).first().click();
  await expect(page.getByRole('combobox', { name: 'Editing tool' })).toHaveValue('photocraft');
  await expect(page.getByRole('switch', { name: /Paint an area/ })).toHaveCount(0);
  await page
    .locator('input[type=file]')
    .setInputFiles({
      name: 'test.png',
      mimeType: 'image/png',
      buffer: Buffer.from(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=',
        'base64',
      ),
    });
  await page.getByRole('button', { name: 'Professional polish' }).click();
  await page.getByRole('button', { name: 'Apply edit' }).click();
  await expect(page.getByRole('link', { name: 'Download PSD' })).toHaveAttribute(
    'href',
    '/api/photocraft/photocraft_ui.png/download',
  );
  await expect(page.getByRole('button', { name: 'Open in PhotoCraft' })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Editing tool' })).toBeEnabled();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: '../docs/screenshots/photocraft-mobile.png', fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.screenshot({ path: '../docs/screenshots/photocraft-desktop.png', fullPage: true });
  await page.getByRole('combobox', { name: 'Editing tool' }).selectOption('kontext');
  await expect(page.getByRole('switch', { name: /Paint an area/ })).toBeVisible();
  expect(errors).toEqual([]);
});
