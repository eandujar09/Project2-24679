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
  await expect.poll(async () => (await state(page)).busy, {timeout:45000}).toBe(false);
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

async function chooseCard(page,label) {
  const form = page.locator('.choice-form').filter({has:page.locator('fieldset:not([disabled])')});
  await form.getByRole('radio',{name:label,exact:true}).check();
  await form.getByRole('button',{name:'Continue',exact:true}).click();
  await settled(page);
}

test('Choice cards construct actual subtracted fluid CAD, retain the source, and disclose context on demand', async ({page}) => {
  const errors = [];
  page.on('pageerror',error => errors.push(error.message));
  await page.goto('/');
  await page.getByLabel('Upload STEP file').setInputFiles(visualFixture);
  await expect(page.getByTestId('cad-viewport')).toHaveAttribute('data-model-id',/.+/);
  const source = (await state(page)).context.modelId;
  await expect(page.getByRole('radio',{name:'Fluid dynamics',exact:true})).toBeEnabled();
  const initialDetail = page.locator('details.message-context').first();
  await expect(initialDetail).not.toHaveAttribute('open','');
  await initialDetail.locator('summary').click();
  await expect(initialDetail).toContainText('Opened');
  await chooseCard(page,'Fluid dynamics');
  await chooseCard(page,'Box around obstacle');
  await expect(page.locator('.assistant-exchange').last()).toContainText('Choose the enclosure sizing.');
  const context = page.locator('.assistant-exchange').last().locator('details.message-context');
  await context.locator('summary').click();
  await expect(context).toContainText('CFD domain-size independence');
  await chooseCard(page,'Suggest clearance');
  await confirm(page); // save exact suggested dimensions, not construction
  expect((await state(page)).context.modelId).toBe(source);
  await chooseCard(page,'Create fluid geometry');
  await expect(page.getByTestId('confirmation-card')).toContainText('Subtract the uploaded obstacle');
  expect((await state(page)).context.modelId).toBe(source);
  await confirm(page); // actual OpenCascade worker, not a synthetic solver
  await expect(page.getByTestId('cad-viewport')).toHaveAttribute('data-fluid-domain','true');
  await expect.poll(async () => (await state(page)).context.modelId).not.toBe(source);
  const current = await state(page);
  await expect(page.getByTestId('cad-viewport')).toHaveAttribute('data-model-id',current.context.modelId);
  expect(current.context.domainGeneration.watertight).toBe(true);
  expect(current.context.domainGeneration.connectedRegions).toBe(1);
  expect(current.context.boundaryConditions).toHaveLength(0);
  expect(current.projects.some(p => p.modelId === source)).toBe(true);
  const download = page.waitForEvent('download');
  await page.getByRole('link',{name:'Fluid geometry (.step)',exact:true}).click();
  expect((await download).suggestedFilename()).toBe('fluid-domain.step');
  await page.screenshot({path:'test-results/studio-created-fluid-domain.png'});
  await page.reload();
  await expect(page.getByTestId('cad-viewport')).toHaveAttribute('data-fluid-domain','true');
  await expect(page.getByTestId('cad-viewport')).toHaveAttribute('data-model-id',current.context.modelId);
  expect(errors).toEqual([]);
});

test('Upload asks for simulation intent, then supports a user-defined pipe domain', async ({page}) => {
  await page.goto('/');
  await page.getByLabel('Upload STEP file').setInputFiles(fixture);
  await expect(page.getByTestId('cad-viewport')).toHaveAttribute('data-model-id', /.+/);
  await expect(page.locator('.chat-scroll')).toContainText('mechanical');
  await expect(page.locator('.chat-scroll')).toContainText('heat transfer');
  await expect(page.locator('.chat-scroll')).toContainText('fluid dynamics');
  await send(page,'Fluid dynamics');
  await expect(page.locator('.chat-scroll')).toContainText('cylindrical/pipe domain');
  expect((await state(page)).context.simulationIntent.type).toBe('fluid');
  expect((await state(page)).context.fluidDomain).toBeNull();
  await send(page,'Define demo pipe domain');
  expect((await state(page)).context.fluidDomain).toBeNull();
  await confirm(page);
  const domain = (await state(page)).context.fluidDomain;
  expect(domain.kind).toBe('cylinder');
  expect(domain.parameters.radius).toBe(10);
  expect(domain.status).toBe('needs_preparation');
});

test('Heat-transfer face symbols preview, confirm and persist without changing the layout', async ({page}) => {
  const errors = [];
  page.on('pageerror',error => errors.push(error.message));
  await page.goto('/');
  await page.getByLabel('Upload STEP file').setInputFiles(visualFixture);
  await expect(page.getByTestId('cad-viewport')).toHaveAttribute('data-model-id', /.+/);
  await send(page,'Heat transfer');
  expect((await state(page)).context.simulationIntent.type).toBe('heat_transfer');
  for (const [face,prompt,label] of [[1,'Apply demo temperature','80 °C'],[2,'Apply demo heat flux','500 W/m²'],[3,'Apply demo convection','15 W/(m² K)'],[4,'Apply demo radiation','ε 0.8'],[5,'Apply demo insulation','Adiabatic']]) {
    await selectFace(page,face);
    await send(page,prompt);
    await expect(page.locator('.boundary-label.proposed')).toContainText(label);
    await confirm(page);
  }
  await expect(page.locator('.boundary-label')).toHaveCount(5);
  await page.screenshot({path:'test-results/studio-thermal-boundaries.png'});
  await page.reload();
  await expect(page.locator('.boundary-label')).toHaveCount(5);
  await page.getByRole('button',{name:'Simulation setup',exact:true}).click();
  await expect(page.locator('.condition-row')).toHaveCount(5);
  await expect(page.locator('.condition-row').filter({hasText:'Convection'})).toContainText('ambient 25 °C');
  expect(errors).toEqual([]);
});

test('Fluent uses the existing chat, previews, SI labels and download flow without new controls', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByLabel('Upload STEP file').setInputFiles(fixture);
  await expect(page.getByTestId('cad-viewport')).toHaveAttribute('data-model-id', /.+/);
  await send(page, 'Configure demo fluid with explicit synthetic test assumptions');
  expect((await state(page)).context.fluentAnalysis).toBeNull();
  await confirm(page);
  expect((await state(page)).context.fluentAnalysis.density).toBe(1);
  for (const [face, prompt, label] of [[1, 'Apply demo wall', 'No-slip wall'], [2, 'Apply demo outlet', '0 Pa gauge'], [3, 'Apply demo inlet', 'm/s']]) {
    await selectFace(page, face);
    await send(page, prompt);
    await expect(page.locator('.boundary-label.proposed')).toContainText(label);
    await confirm(page);
  }
  await page.getByRole('button', { name: 'Simulation setup', exact: true }).click();
  await expect(page.locator('.condition-row')).toHaveCount(3);
  await expect(page.locator('.condition-row').filter({hasText:'Pressure outlet'})).toContainText('0 Pa gauge');
  await expect(page.locator('.condition-row').filter({hasText:'Velocity inlet'})).toContainText('m/s');
  await page.getByRole('button', { name: 'Close Simulation setup' }).click();
  await send(page, 'Run Fluent simulation');
  expect((await state(page)).context.lastResult).toBeNull();
  await expect(page.locator('.message-code')).toContainText('ctx.solve()');
  await confirm(page);
  expect((await state(page)).context.lastResult.solver).toBe('fluent');
  await expect(page.locator('.message-image img')).toHaveCount(2);
  await expect(page.getByRole('button', {name:'Export setup (.mechdat)',exact:true})).toBeDisabled();
  await expect(page.getByRole('button', {name:'Export solved simulation (.mechpz)',exact:true})).toBeDisabled();
  await page.reload();
  await expect(page.locator('.boundary-label')).toHaveCount(3);
  expect(errors).toEqual([]);
});

test('Gravity previews and applied arrows match the design axes through orbit, rejection and disabling', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByLabel('Upload STEP file').setInputFiles(path.resolve('examples/simple-bracket/simple-bracket.step'));
  const viewport = page.getByTestId('cad-viewport');
  await expect(viewport).toHaveAttribute('data-model-id', /.+/);
  await expect(viewport).toHaveAttribute('data-design-axes', /"axis":"Z"/);
  await expect(page.locator('.gravity-status')).toHaveCount(0);
  await send(page, 'Enable gravity toward negative Z');
  await expect(page.locator('.gravity-label.proposed')).toContainText('Proposed gravity · −Z');
  await expect(page.locator('.gravity-label')).toHaveAttribute('data-gravity-vector', '[0,0,-9.80665]');
  await expect(page.locator('.gravity-status')).toContainText('9.8066 m/s²');
  await page.screenshot({ path: 'test-results/studio-gravity-proposed.png' });
  await send(page, 'No, let me check');
  await expect(page.locator('.gravity-label')).toHaveCount(0);
  await send(page, 'Enable gravity toward negative Z');
  await confirm(page);
  await expect(page.locator('.gravity-label')).toHaveAttribute('data-condition-state', 'applied');
  await page.getByRole('button', { name: 'Top view', exact: true }).click();
  await expect.poll(async () => {
    const axes = JSON.parse(await viewport.getAttribute('data-design-axes'));
    return Math.hypot(...axes.find(a => a.axis === 'Z').screen.slice(0, 2));
  }).toBeLessThan(.001);
  const before = await viewport.getAttribute('data-design-axes');
  await page.getByRole('button', { name: 'Isometric view', exact: true }).click();
  await expect.poll(() => viewport.getAttribute('data-design-axes')).not.toBe(before);
  const rect = await viewport.boundingBox();
  await page.mouse.move(rect.x + rect.width * .5, rect.y + rect.height * .5);
  await page.mouse.down();
  await page.mouse.move(rect.x + rect.width * .7, rect.y + rect.height * .6, { steps: 12 });
  await page.mouse.up();
  await expect(page.locator('.gravity-label')).toHaveAttribute('data-gravity-vector', '[0,0,-9.80665]');
  await page.getByRole('button', { name: 'Isometric view', exact: true }).click();
  await page.screenshot({ path: 'test-results/studio-gravity-applied.png' });
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Save viewport image', exact: true }).click();
  await (await download).saveAs('test-results/studio-gravity-viewport.png');
  await send(page, 'Reverse gravity toward positive Z');
  await expect(page.locator('.gravity-label.proposed')).toContainText('+Z');
  await send(page, 'No, keep negative Z');
  await expect(page.locator('.gravity-label')).toContainText('−Z');
  await page.reload();
  await expect(page.locator('.gravity-label')).toHaveAttribute('data-condition-state', 'applied');
  await page.getByLabel('Assistant mode').selectOption('autonomous');
  await send(page, 'Disable gravity');
  await expect(page.locator('.gravity-label')).toHaveCount(0);
  await expect(page.locator('.gravity-status')).toHaveCount(0);
  await expect(viewport).toHaveAttribute('data-design-axes', /"axis":"X"/);
  await send(page, 'Enable gravity toward negative Z');
  await expect(page.locator('.gravity-label')).toHaveAttribute('data-condition-state', 'applied');
  await page.getByLabel('Upload STEP file').setInputFiles(visualFixture);
  await expect(page.locator('.gravity-label')).toHaveCount(0);
  await expect(viewport).toHaveAttribute('data-design-axes', /"axis":"Z"/);
  expect(errors).toEqual([]);
});

test('Shared face state, chat confirmations, generated code and result downloads', async ({ page }) => {
  // HTTP Tailscale addresses do not expose the secure-context randomUUID API.
  await page.addInitScript(() => Object.defineProperty(Crypto.prototype, 'randomUUID', { value: undefined }));
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('.studio-app')).toHaveAttribute('data-session-id', /[a-f0-9]{32}/);
  const setupExport = page.getByRole('button', { name: 'Export setup (.mechdat)', exact: true });
  const solvedExport = page.getByRole('button', { name: 'Export solved simulation (.mechpz)', exact: true });
  await expect(setupExport).toBeDisabled();
  await expect(solvedExport).toBeDisabled();
  await page.getByLabel('Upload STEP file').setInputFiles(fixture);
  await expect(page.getByTestId('cad-viewport')).toHaveAttribute('data-model-id', /.+/);
  await expect(setupExport).toBeDisabled();
  await expect(solvedExport).toBeDisabled();
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
  await expect(setupExport).toBeEnabled();
  await expect(solvedExport).toBeDisabled();
  const setupDownload = page.waitForEvent('download');
  await setupExport.click();
  expect((await setupDownload).suggestedFilename()).toBe('setup.mechdat');
  await settled(page);
  await expect(solvedExport).toBeDisabled();

  await send(page, 'Compare mesh sizes and check convergence');
  await expect(page.locator('.message-code')).toContainText('Generated mesh study');
  expect((await state(page)).context.lastResult).toBeNull();
  await confirm(page);
  await expect(page.locator('.message-image img')).toHaveCount(2);
  await expect(page.locator('.message-image img').first()).toBeVisible();
  expect(await page.locator('.message-image img').first().evaluate(im => im.complete && im.naturalWidth > 0)).toBe(true);
  const comparison = page.locator('details.message-context').filter({has:page.locator('.markdown table')});
  await comparison.locator('summary').click();
  await expect(comparison.locator('.markdown table')).toBeVisible();
  await expect(solvedExport).toBeEnabled();
  const nativeDownload = page.waitForEvent('download');
  await solvedExport.click();
  expect((await nativeDownload).suggestedFilename()).toBe('simulation.mechpz');
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
