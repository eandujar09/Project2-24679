import { test, expect } from '@playwright/test';
import { createRequire } from 'node:module';
import { buildFaceMap, meshOccurrences } from '../../src/cad/faceMap.js';

const require = createRequire(import.meta.url);
let cube;
let rounded;
test.beforeAll(async () => {
  async function sample(path) {
    const response = await fetch(`https://raw.githubusercontent.com/kovacsv/occt-import-js/main/test/testfiles/${path}`);
    if (!response.ok) throw new Error(`Could not fetch upstream STEP fixture: ${response.status}`);
    return Buffer.from(await response.arrayBuffer());
  }
  [cube, rounded] = await Promise.all([sample('simple-basic-cube/cube.stp'), sample('rounded-cube/rounded-cube.step')]);
});

test('real OpenCascade metadata covers cube and curved faces completely', async () => {
  const occt = await require('occt-import-js')();
  expect(rounded.toString()).toContain('CYLINDRICAL_SURFACE');
  for (const [buffer, curved] of [[cube, false], [rounded, true]]) {
    const result = occt.ReadStepFile(buffer, null);
    expect(result.success).toBe(true);
    let hasCurvedFace = false;
    let count = 0;
    for (const occurrence of meshOccurrences(result)) {
      const { faces, triangleToFaceKey } = buildFaceMap(occurrence.mesh, occurrence.componentKey);
      count += faces.length;
      for (const face of faces) {
        expect(triangleToFaceKey.slice(face.first, face.last + 1).every(key => key === face.key)).toBe(true);
        if (face.last - face.first > 2) hasCurvedFace = true;
      }
    }
    if (curved) expect(hasCurvedFace).toBe(true);
    else expect(count).toBe(6);
  }
});

test('production viewer supports picking, CRUD, persistence, JSON transfer, and errors', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await page.locator('#step-file').setInputFiles({ name: 'cube.stp', mimeType: 'application/octet-stream', buffer: cube });
  await expect(page.locator('#loading')).toBeHidden();
  await expect(page.locator('#model-status')).toContainText('6 faces');
  await expect(page.locator('#save-status')).toHaveText('Saved locally');
  const canvas = page.locator('canvas');
  const rect = await canvas.boundingBox();
  await canvas.click({ position: { x: rect.width / 2, y: rect.height / 2 } });
  await expect(page.locator('#face-key')).not.toHaveText('No face selected');
  const selectedKey = await page.locator('#face-key').textContent();
  await page.locator('#comment-text').fill('<script>Review mounting surface</script>');
  await page.locator('#save-comment').click();
  await expect(page.locator('.comment-card')).toHaveCount(1);
  await expect(page.locator('.comment-card p')).toHaveText('<script>Review mounting surface</script>');
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await page.locator('#comment-text').fill('Updated surface finish');
  await page.locator('#save-comment').click();
  await expect(page.locator('.comment-card p')).toHaveText('Updated surface finish');
  // Adding a second comment to the same original face is supported.
  await page.locator('#comment-text').fill('Second note');
  await page.locator('#save-comment').click();
  await expect(page.locator('.comment-card')).toHaveCount(2);
  const downloadEvent = page.waitForEvent('download');
  await page.locator('#export').click();
  const download = await downloadEvent;
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  const exported = JSON.parse(Buffer.concat(chunks).toString());
  expect(exported.comments).toHaveLength(2);
  expect(exported.comments.every(c => c.faceKey === selectedKey)).toBe(true);
  await page.reload();
  await page.locator('#reopen').click();
  await expect(page.locator('#loading')).toBeHidden();
  await expect(page.locator('.comment-card')).toHaveCount(2);
  await page.locator('.comment-jump').first().click();
  await expect(page.locator('#face-key')).toHaveText(selectedKey);
  await page.keyboard.press('Escape');
  await expect(page.locator('#face-key')).toHaveText('No face selected');
  const invalid = { ...exported, modelId: 'different-file-hash' };
  await page.locator('#json-file').setInputFiles({ name: 'wrong.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(invalid)) });
  await expect(page.locator('#error')).toContainText('SHA-256 mismatch');
  await expect(page.locator('.comment-card')).toHaveCount(2);
  page.on('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Delete', exact: true }).first().click();
  await expect(page.locator('.comment-card')).toHaveCount(1);
  await page.locator('#json-file').setInputFiles({ name: 'notes.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(exported)) });
  await expect(page.locator('.comment-card')).toHaveCount(2);
  await page.locator('#step-file').setInputFiles({ name: 'invalid.step', mimeType: 'application/octet-stream', buffer: Buffer.from('invalid geometry') });
  await expect(page.locator('#loading')).toBeHidden();
  await expect(page.locator('#error')).toContainText('Could not open STEP');
  await expect(page.locator('#model-status')).toContainText('cube.stp');
  expect(errors).toEqual([]);
});

test('curved STEP loads and face navigation works on a narrow screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.locator('#step-file').setInputFiles({ name: 'rounded.step', mimeType: 'application/octet-stream', buffer: rounded });
  await expect(page.locator('#loading')).toBeHidden();
  await expect(page.locator('#fit')).toBeEnabled();
  const key = await page.locator('#face-picker option').nth(1).getAttribute('value');
  await page.locator('#face-picker').selectOption(key);
  await expect(page.locator('#face-key')).toHaveText(key);
  await page.locator('#boundary-type').selectOption('pressure');
  await page.locator('#boundary-save').click();
  await expect(page.locator('.boundary-card')).toHaveCount(1);
  await expect(page.locator('.boundary-label')).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('dragging does not select, face changes bind new comments correctly, and latest import wins', async ({ page }) => {
  await page.goto('/');
  const input = page.locator('#step-file');
  await input.setInputFiles({ name: 'cube.stp', mimeType: 'application/octet-stream', buffer: cube });
  await expect(page.locator('#fit')).toBeEnabled();
  const rect = await page.locator('canvas').boundingBox();
  const center = { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
  await page.mouse.move(center.x, center.y);
  await page.mouse.down();
  await page.mouse.move(center.x + 90, center.y + 30, { steps: 10 });
  await page.mouse.move(center.x, center.y, { steps: 10 });
  await page.mouse.up();
  await expect(page.locator('#face-key')).toHaveText('No face selected');
  const options = page.locator('#face-picker option');
  const first = await options.nth(1).getAttribute('value');
  const second = await options.nth(2).getAttribute('value');
  await page.locator('#face-picker').selectOption(first);
  await page.locator('#comment-text').fill('Draft for old face');
  await page.locator('#face-picker').selectOption(second);
  await expect(page.locator('#comment-text')).toHaveValue('');
  await page.locator('#comment-text').fill('Comment for second face');
  await page.locator('#save-comment').click();
  await expect(page.locator('.comment-card')).toHaveCount(1);
  await page.locator('#face-picker').selectOption(first);
  await page.locator('.comment-jump').click();
  await expect(page.locator('#face-key')).toHaveText(second);
  await input.setInputFiles({ name: 'old-rounded.step', mimeType: 'application/octet-stream', buffer: rounded });
  await input.setInputFiles({ name: 'latest.stp', mimeType: 'application/octet-stream', buffer: cube });
  await expect(page.locator('#loading')).toBeHidden();
  await expect(page.locator('#model-status')).toContainText('latest.stp');
  await expect(page.locator('#model-status')).toContainText('6 faces');
  await expect(page.locator('.comment-card')).toHaveCount(1);
});

test('boundary conditions have face visuals, editing, local restore and validated JSON transfer', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await expect(page.locator('#boundary-save')).toBeDisabled();
  await page.locator('#step-file').setInputFiles({ name: 'cube.stp', mimeType: 'application/octet-stream', buffer: cube });
  await expect(page.locator('#fit')).toBeEnabled();
  const canvas = page.locator('canvas');
  const rect = await canvas.boundingBox();
  await canvas.click({ position: { x: rect.width / 2, y: rect.height / 2 } });
  const faceKey = await page.locator('#face-key').textContent();
  const before = await canvas.screenshot();
  await page.locator('#boundary-save').click();
  await expect(page.locator('.boundary-card')).toHaveCount(1);
  await expect(page.locator('.boundary-label')).toBeVisible();
  await expect(page.locator('.boundary-label')).toContainText('Fixed support');
  expect(Buffer.compare(before, await canvas.screenshot())).not.toBe(0);
  await page.locator('#boundary-type').selectOption('force');
  await page.locator('#boundary-save').click();
  await expect(page.locator('#error')).toContainText('nonzero');
  await page.locator('#boundary-x').fill('-20');
  await page.locator('#boundary-save').click();
  await expect(page.locator('.boundary-card')).toHaveCount(2);
  await page.locator('#boundary-type').selectOption('displacement');
  await page.locator('#boundary-z').fill('0.5');
  await page.locator('#boundary-save').click();
  await expect(page.locator('.boundary-card')).toHaveCount(3);
  await page.locator('#boundary-type').selectOption('pressure');
  await page.locator('#boundary-magnitude').fill('2.5');
  await page.locator('#boundary-save').click();
  await expect(page.locator('.boundary-card')).toHaveCount(4);
  const force = page.locator('.boundary-card').filter({ has: page.locator('.boundary-jump', { hasText: 'Force' }) });
  await force.getByRole('button', { name: 'Edit condition' }).click();
  await page.locator('#boundary-x').fill('-40');
  await page.locator('#boundary-save').click();
  await expect(force).toContainText('X -40');
  const event = page.waitForEvent('download');
  await page.locator('#export').click();
  const download = await event;
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  const exported = JSON.parse(Buffer.concat(chunks).toString());
  expect(exported.schemaVersion).toBe(2);
  expect(exported.boundaryConditions).toHaveLength(4);
  expect(exported.boundaryConditions.every(c => c.faceKey === faceKey)).toBe(true);
  await page.reload();
  await page.locator('#reopen').click();
  await expect(page.locator('.boundary-card')).toHaveCount(4);
  await expect(page.locator('.boundary-label')).toHaveCount(4);
  await page.locator('.boundary-jump').first().click();
  await expect(page.locator('#face-key')).toHaveText(faceKey);
  await page.keyboard.press('Escape');
  await expect(page.locator('.boundary-label')).toHaveCount(4);
  page.on('dialog', dialog => dialog.accept());
  await page.locator('.boundary-card').filter({ has: page.locator('.boundary-jump', { hasText: 'Pressure' }) }).getByRole('button', { name: 'Remove condition' }).click();
  await expect(page.locator('.boundary-card')).toHaveCount(3);
  await expect(page.locator('.boundary-label')).toHaveCount(3);
  async function importData(data) {
    await page.locator('#json-file').setInputFiles({ name: 'conditions.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(data)) });
    await expect(page.locator('#import')).toBeEnabled();
  }
  await importData(exported);
  await expect(page.locator('.boundary-card')).toHaveCount(4);
  await importData({ ...exported, modelId: 'wrong-hash' });
  await expect(page.locator('#error')).toContainText('SHA-256 mismatch');
  const malformed = structuredClone(exported);
  malformed.boundaryConditions.find(c => c.type === 'force').values.x = 'invalid';
  await importData(malformed);
  await expect(page.locator('#error')).toContainText('finite numbers');
  await expect(page.locator('.boundary-card')).toHaveCount(4);
  await importData({ schemaVersion: 1, modelId: exported.modelId, filename: exported.filename, comments: [] });
  await expect(page.locator('.boundary-card')).toHaveCount(4);
  await page.locator('#step-file').setInputFiles({ name: 'rounded.step', mimeType: 'application/octet-stream', buffer: rounded });
  await expect(page.locator('#model-status')).toContainText('rounded.step');
  await expect(page.locator('.boundary-card')).toHaveCount(0);
  await expect(page.locator('.boundary-label')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('database upgrade preserves existing version-one models and comments', async ({ page }) => {
  await page.route('**/assets/*.js', route => route.fulfill({ contentType: 'application/javascript', body: '' }));
  await page.goto('/');
  await page.evaluate(async bytes => {
    const blob = new Blob([new Uint8Array(bytes)]);
    const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
    const id = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
    await new Promise((resolve, reject) => {
      const request = indexedDB.open('step-face-comments', 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        db.createObjectStore('models', { keyPath: 'id' });
        const comments = db.createObjectStore('comments', { keyPath: 'id' });
        comments.createIndex('modelId', 'modelId');
        comments.createIndex('modelFace', ['modelId', 'faceKey']);
        db.createObjectStore('settings');
      };
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const db = request.result;
        const tx = db.transaction(['models', 'comments', 'settings'], 'readwrite');
        tx.objectStore('models').put({ id, filename: 'legacy.stp', importedAt: new Date().toISOString(), fileBlob: blob });
        tx.objectStore('comments').put({ id: 'legacy-comment', modelId: id, faceKey: 'legacy-face', text: 'Existing review preserved', createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() });
        tx.objectStore('settings').put(id, 'lastModel');
        tx.oncomplete = () => { db.close(); resolve(); };
        tx.onerror = () => reject(tx.error);
      };
    });
  }, [...cube]);
  await page.unroute('**/assets/*.js');
  await page.reload();
  await page.locator('#reopen').click();
  await expect(page.locator('#model-status')).toContainText('legacy.stp');
  await expect(page.locator('.comment-card')).toContainText('Existing review preserved');
  const key = await page.locator('#face-picker option').nth(1).getAttribute('value');
  await page.locator('#face-picker').selectOption(key);
  await page.locator('#boundary-save').click();
  await expect(page.locator('.boundary-card')).toHaveCount(1);
});
