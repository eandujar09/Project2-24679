import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

let fixture, visualFixture;
test.beforeAll(() => {
  const directory = path.resolve('test-results/studio-fixtures');
  mkdirSync(directory, { recursive: true });
  fixture = path.join(directory, 'cylinder.step');
  const python = process.env.GRADIO_TEST_PYTHON || '.venv-gradio/bin/python';
  execFileSync(python, ['-c', `
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
import sys
writer = STEPControl_Writer()
writer.Transfer(BRepPrimAPI_MakeCylinder(5, 20).Shape(), STEPControl_AsIs)
writer.Write(sys.argv[1])
`, fixture]);
  visualFixture = path.join(directory, 'visual-box.step');
  execFileSync(python, ['-c', `
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
import sys
writer = STEPControl_Writer()
writer.Transfer(BRepPrimAPI_MakeBox(20, 15, 10).Shape(), STEPControl_AsIs)
writer.Write(sys.argv[1])
`, visualFixture]);
});

async function state(page) {
  return page.evaluate(async () => (await fetch('/api/studio/sessions/' + sessionStorage.getItem('studio-session'))).json());
}
async function settled(page) {
  await expect.poll(async () => (await state(page)).busy).toBe(false);
}
async function send(page, text) {
  await settled(page);
  await page.getByRole('textbox', { name: 'Message the assistant' }).fill(text);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Message the assistant' })).toHaveValue('');
  await settled(page);
}
async function selectFace(page, index) {
  await page.getByRole('button', { name: 'Model', exact: true }).click();
  await page.locator('.face-row').filter({ has: page.getByText(`Face ${index}`, { exact: true }) }).click();
  await expect(page.getByTestId('selected-face')).toContainText('Face ' + index);
  await page.getByRole('button', { name: 'Close Model', exact: true }).click();
  await settled(page);
}
async function confirm(page) {
  await expect(page.getByTestId('confirmation-card')).toBeVisible();
  await page.getByRole('button', { name: 'Confirm', exact: true }).click();
  await expect(page.getByTestId('confirmation-card')).toHaveCount(0);
  await settled(page);
}

test('Shared face state, chat confirmations, generated code and result downloads', async ({ page }) => {
  // HTTP Tailscale addresses do not expose the secure-context randomUUID API.
  await page.addInitScript(() => Object.defineProperty(Crypto.prototype, 'randomUUID', { value: undefined }));
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('.studio-app')).toHaveAttribute('data-session-id', /[a-f0-9]{32}/);
  await page.getByLabel('Upload STEP file').setInputFiles(fixture);
  await expect(page.getByTestId('cad-viewport')).toHaveAttribute('data-model-id', /.+/);
  await page.getByTestId('cad-viewport').locator('canvas').click();
  await expect(page.getByTestId('selected-face')).toBeVisible();
  await settled(page);
  await selectFace(page, 1);
  const first = await state(page);
  const context = await page.evaluate(async uri => {
    const r = await fetch('/mcp/', { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'resources/read', params: { uri } }) });
    return JSON.parse((await r.json()).result.contents[0].text);
  }, first.context.uri);
  expect(context.selectedFace.key).toBe(first.context.selectedFace.key);

  await send(page, 'Fix this face');
  expect((await state(page)).context.boundaryConditions).toHaveLength(0);
  await expect(page.locator('.boundary-label.proposed')).toContainText('Proposed · Fixed support');
  await expect(page.locator('.boundary-label.proposed')).toBeVisible();
  await page.screenshot({ path: 'test-results/studio-proposed-support.png' });
  // Rejection removes the preview without saving a support; confirmation stays in chat.
  await send(page, 'No, let me reconsider');
  await expect(page.locator('.boundary-label.proposed')).toHaveCount(0);
  expect((await state(page)).context.boundaryConditions).toHaveLength(0);
  await send(page, 'Fix this face');
  await confirm(page);
  await expect(page.locator('.boundary-label.proposed')).toHaveCount(0);
  await expect(page.locator('.boundary-label[data-condition-state="applied"]')).toHaveCount(1);
  await expect.poll(async () => (await state(page)).context.boundaryConditions.length).toBe(1);
  await send(page, 'Highlight face 2');
  await expect(page.locator('.highlight-info')).toContainText('Face 2');
  await expect(page.getByTestId('selected-face')).toContainText('Face 1');
  await selectFace(page, 2);
  await send(page, 'Apply 100 N along +Z');
  await expect(page.locator('.boundary-label.proposed')).toContainText('Proposed · Force · X 0, Y 0, Z 100 N');
  await expect(page.locator('.boundary-label.proposed')).toBeVisible();
  expect((await state(page)).context.boundaryConditions).toHaveLength(1);
  await page.screenshot({ path: 'test-results/studio-proposed-force.png' });
  await confirm(page);
  await expect(page.locator('.boundary-label.proposed')).toHaveCount(0);
  await expect(page.locator('.boundary-label[data-condition-state="applied"]')).toHaveCount(2);
  await send(page, 'Change force to 200 N');
  await expect(page.locator('.boundary-label')).toHaveCount(2);
  await expect(page.locator('.boundary-label.proposed')).toContainText('Z 200 N');
  expect((await state(page)).context.boundaryConditions.find(b => b.type === 'force').values.z).toBe(100);
  await send(page, 'No, keep the original load');
  await expect(page.locator('.boundary-label.proposed')).toHaveCount(0);
  await expect(page.locator('.boundary-label').filter({ hasText: 'Force' })).toContainText('Z 100 N');
  await send(page, 'Use Structural Steel and small deformations');
  await confirm(page);
  await page.getByRole('button', { name: 'Simulation setup', exact: true }).click();
  await expect(page.locator('.condition-row')).toHaveCount(2);
  await expect(page.locator('.setup-details')).toContainText('Structural Steel');
  await page.getByRole('button', { name: 'Close Simulation setup' }).click();

  await send(page, 'Compare mesh sizes and check convergence');
  await expect(page.locator('.message-code')).toContainText('Generated mesh study');
  expect((await state(page)).context.lastResult).toBeNull();
  await confirm(page);
  await expect(page.locator('.message-image img')).toHaveCount(2);
  await expect(page.locator('.message-image img').first()).toBeVisible();
  expect(await page.locator('.message-image img').first().evaluate(im => im.complete && im.naturalWidth > 0)).toBe(true);
  await expect(page.locator('.markdown table')).toBeVisible();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download simulation', exact: true }).click();
  expect((await downloadPromise).suggestedFilename()).toBe('simulation.zip');
  const sid = (await state(page)).context.sessionId;
  await page.reload();
  await expect(page.locator('.message-image img')).toHaveCount(2);
  expect((await state(page)).context.sessionId).toBe(sid);
  await page.getByRole('button', { name: 'New conversation', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'New conversation', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Let’s set up your simulation.' })).toBeVisible();
  const after = await state(page);
  expect(after.context.boundaryConditions).toHaveLength(2);
  expect(after.context.programAttempts).toHaveLength(1);
  expect(errors).toEqual([]);
});

test('A proposal pivots to the hidden back face without selecting or applying it', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.studio-app')).toHaveAttribute('data-session-id', /[a-f0-9]{32}/);
  await page.getByLabel('Upload STEP file').setInputFiles(path.resolve('examples/simple-bracket/simple-bracket.step'));
  await expect(page.getByTestId('cad-viewport')).toHaveAttribute('data-model-id', /.+/);
  await send(page, 'Fix the back face');
  await expect(page.locator('.boundary-label.proposed')).toBeVisible();
  await expect(page.getByTestId('confirmation-card')).toBeVisible();
  expect((await state(page)).context.selectedFace).toBeNull();
  expect((await state(page)).context.boundaryConditions).toHaveLength(0);
  // Once the short pivot finishes, the center ray must hit the formerly hidden
  // back face. This checks the rendered camera, not just a focus flag in state.
  await page.waitForTimeout(550);
  await page.screenshot({ path: 'test-results/studio-back-face-pivot.png' });
  await page.getByTestId('cad-viewport').locator('canvas').click();
  await expect.poll(async () => (await state(page)).context.selectedFace?.index).toBe(7);
  expect((await state(page)).context.boundaryConditions).toHaveLength(0);
});

test('Included simple bracket, camera tools, layout, theme and mobile', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('.studio-app')).toHaveAttribute('data-session-id', /[a-f0-9]{32}/);
  await page.screenshot({ path: 'test-results/studio-empty.png' });
  const bracket = path.resolve('examples/simple-bracket/simple-bracket.step');
  await page.getByLabel('Upload STEP file').setInputFiles(bracket);
  await expect(page.getByTestId('cad-viewport')).toHaveAttribute('data-model-id', /.+/);
  await expect(page.locator('.model-caption')).toContainText('9 faces');
  await page.getByRole('button', { name: 'Top view', exact: true }).click();
  await page.getByRole('button', { name: 'Isometric view', exact: true }).click();
  await page.screenshot({ path: 'test-results/studio-bracket.png' });
  const imagePromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Save viewport image', exact: true }).click();
  expect((await imagePromise).suggestedFilename()).toBe('cad-view.png');
  await page.getByRole('separator').focus();
  await page.keyboard.press('ArrowLeft');
  await expect(page.getByRole('separator')).toHaveAttribute('aria-valuenow', '48');
  await page.getByRole('button', { name: 'Toggle assistant', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Simulation assistant' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Toggle assistant', exact: true }).click();
  await page.getByRole('button', { name: 'Workspace settings', exact: true }).click();
  await page.getByRole('button', { name: 'Light', exact: true }).click();
  await page.getByRole('button', { name: 'Close Settings' }).click();
  await expect(page.locator('html')).not.toHaveClass('dark');
  await page.screenshot({ path: 'test-results/studio-light.png' });
  await page.getByRole('button', { name: 'Workspace settings', exact: true }).click();
  await page.getByRole('button', { name: 'Dark', exact: true }).click();
  await page.getByRole('button', { name: 'Close Settings' }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('textbox', { name: 'Message the assistant' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/studio-mobile.png' });
  expect(errors).toEqual([]);
});

test('Optional visual screenshots and pixel picks work with either assistant mode', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('.studio-app')).toHaveAttribute('data-session-id', /[a-f0-9]{32}/);
  await page.getByLabel('Upload STEP file').setInputFiles(visualFixture);
  await expect(page.getByTestId('cad-viewport')).toHaveAttribute('data-model-id', /.+/);
  await expect(page.getByLabel('Assistant mode')).toHaveValue('guided');
  await expect(page.getByRole('switch', { name: 'Visual assistance' })).not.toBeChecked();
  await page.getByRole('switch', { name: 'Visual assistance' }).click();
  await expect(page.getByRole('switch', { name: 'Visual assistance' })).toBeChecked();
  await send(page, 'Inspect screenshot without clicking');
  await expect(page.locator('.conversation')).toContainText('I received the viewport screenshot');
  expect((await state(page)).context.highlightedFaceKeys).toEqual([]);
  await send(page, 'Pick screenshot center');
  await expect(page.locator('.highlight-info')).toContainText('Face');
  expect((await state(page)).context.selectedFace).toBeNull();
  await selectFace(page, 1);
  await send(page, 'Fix this face');
  await expect(page.getByTestId('confirmation-card')).toBeVisible();
  await confirm(page);
  expect((await state(page)).context.boundaryConditions).toHaveLength(1);
  await send(page, 'Use Structural Steel and small deformations');
  await expect(page.getByTestId('confirmation-card')).toBeVisible();
  await page.getByLabel('Assistant mode').selectOption('autonomous');
  await expect(page.getByTestId('confirmation-card')).toHaveCount(0);
  expect((await state(page)).context.analysis.material).toBeNull();
  await send(page, 'Use Structural Steel and small deformations');
  expect((await state(page)).context.analysis.material).toBe('Structural Steel');
  await expect(page.getByTestId('confirmation-card')).toHaveCount(0);
  await page.getByRole('switch', { name: 'Visual assistance' }).click();
  await expect(page.getByRole('switch', { name: 'Visual assistance' })).not.toBeChecked();
  expect((await state(page)).context.visualAssistance.frame).toBeNull();
  await send(page, 'Compare mesh sizes and check convergence');
  await expect(page.locator('.message-image img')).toHaveCount(2);
  await page.getByLabel('Assistant mode').selectOption('guided');
  await expect(page.getByLabel('Assistant mode')).toHaveValue('guided');
  await send(page, 'Use Structural Steel and small deformations');
  await expect(page.getByTestId('confirmation-card')).toBeVisible();
  await page.screenshot({ path: 'test-results/studio-visual-mode.png' });
  expect(errors).toEqual([]);
});
