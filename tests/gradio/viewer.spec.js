import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

let fixture;
let simulationFixture;
test.beforeAll(() => {
  const directory = path.resolve('test-results/gradio-fixtures');
  mkdirSync(directory, { recursive: true });
  fixture = path.join(directory, 'cylinder.step');
  simulationFixture = path.join(directory, 'simulation-cylinder.step');
  const python = process.env.GRADIO_TEST_PYTHON || (process.platform === 'win32' ? '.venv-gradio/Scripts/python.exe' : '.venv-gradio/bin/python');
  execFileSync(python, ['-c', `
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
import sys
for target, length in [(sys.argv[1], 20), (sys.argv[2], 24)]:
    writer = STEPControl_Writer()
    writer.Transfer(BRepPrimAPI_MakeCylinder(5, length).Shape(), STEPControl_AsIs)
    writer.Write(target)
`, fixture, simulationFixture]);
});

async function send(page, text) {
  const input = page.getByRole('textbox', { name: 'Message the assistant', exact: true });
  await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeEnabled();
  await input.fill(text);
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(input).toHaveValue('');
  await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeEnabled({ timeout: 15000 });
}

async function confirm(page) {
  await expect(page.getByText('Please confirm this proposal.', { exact: true }).last()).toBeVisible();
  await send(page, 'Confirm');
}

async function readResource(page, uri) {
  return page.evaluate(async uri => {
    const response = await fetch('/mcp/', { method: 'POST', headers: {
      'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'
    }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'resources/read', params: { uri } }) });
    const result = await response.json();
    if (result.error) throw new Error(JSON.stringify(result.error));
    return JSON.parse(result.result.contents[0].text);
  }, uri);
}

test('Chat controls conditions, independent highlights, and result images', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByText('Talk to your model', { exact: true })).toBeVisible();
  await page.locator('input[type=file]').first().setInputFiles(fixture);
  await expect(page.locator('.cad-status')).toContainText('3 CAD faces', { timeout: 30000 });
  const canvas = page.locator('#python-cad-preview canvas');
  await canvas.evaluate(node => { node.dataset.instance = 'original-canvas'; });
  await page.getByText('Choose a face by number', { exact: true }).click();
  const picker = page.getByRole('combobox', { name: 'Select whole CAD face' });
  await picker.click();
  await page.getByRole('option', { name: /Face 3 ·/ }).click();
  await expect(page.locator('#selection-context')).toContainText('Selected: Face 3');
  await expect(page.getByText('I can see your selected face.', { exact: false })).toBeVisible();
  await send(page, 'Fix this face');
  const sid = await page.locator('.python-cad-viewer').getAttribute('data-session-id');
  let context = await readResource(page, `cad://session/${sid}/context`);
  expect(context.boundaryConditions).toHaveLength(0);
  expect(context.pendingConfirmation.tool).toBe('apply_condition');
  await expect(page.locator('.python-cad-viewer')).toHaveAttribute('data-highlighted-faces', '["python-ocp-v1:face:3"]');
  await confirm(page);
  await expect(page.locator('.boundary-label')).toContainText('Fixed support');
  context = await readResource(page, `cad://session/${sid}/context`);
  expect(context.selectedFace.index).toBe(3);
  expect(context.boundaryConditions).toHaveLength(1);
  await send(page, 'Highlight face 2');
  await expect(page.locator('.python-cad-viewer')).toHaveAttribute('data-highlighted-faces', '["python-ocp-v1:face:2"]');
  await expect(picker).toHaveValue(/Face 3/);
  await picker.click();
  await page.getByRole('option', { name: /Face 2 ·/ }).click();
  await send(page, 'Apply 100 N in global +Z to this face');
  await confirm(page);
  await expect(page.locator('.boundary-label').filter({ hasText: '100' })).toBeVisible();
  await send(page, 'Use Structural Steel and small deformation');
  await confirm(page);
  await send(page, 'Run simulation');
  expect((await readResource(page, `cad://session/${sid}/context`)).lastResult).toBeNull();
  await confirm(page);
  await expect(page.getByText('Simulation complete.', { exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.locator('img[src*="totalDeformation"]')).toBeVisible();
  await expect(page.locator('img[src*="vonMisesStress"]')).toBeVisible();
  context = await readResource(page, `cad://session/${sid}/context`);
  expect(context.lastResult.status).toBe('succeeded');
  await expect(canvas).toHaveAttribute('data-instance', 'original-canvas');
  await page.screenshot({ path: 'test-results/chat-ui.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('A canvas click updates the MCP resource and clearing selection keeps it in sync', async ({ page }) => {
  await page.goto('/');
  await page.locator('input[type=file]').first().setInputFiles(simulationFixture);
  await expect(page.locator('.cad-status')).toContainText('3 CAD faces', { timeout: 30000 });
  const canvas = page.locator('#python-cad-preview canvas');
  const box = await canvas.boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page.locator('#selection-context')).toContainText('Selected: Face');
  const sid = await page.locator('.python-cad-viewer').getAttribute('data-session-id');
  expect((await readResource(page, `cad://session/${sid}/context`)).selectedFace).not.toBeNull();
  await page.getByRole('button', { name: 'Clear face', exact: true }).click();
  await expect(page.locator('#selection-context')).toContainText('No face selected');
  expect((await readResource(page, `cad://session/${sid}/context`)).selectedFace).toBeNull();
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.locator('.cad-status')).toContainText('3 CAD faces');
  await send(page, 'Run simulation');
  await confirm(page);
  await expect(page.getByText('More information is needed:', { exact: false })).toBeVisible();
  expect((await readResource(page, `cad://session/${sid}/context`)).lastResult).toBeNull();
});


test('Generated Python, convergence table, images and source download appear in chat', async ({ page }) => {
  await page.goto('/');
  await page.locator('input[type=file]').first().setInputFiles(fixture);
  await expect(page.locator('.cad-status')).toContainText('3 CAD faces', { timeout: 30000 });
  await send(page, 'Compare mesh sizes and check convergence');
  await expect(page.locator('pre code')).toContainText('for size in [6, 4, 3]');
  const sid = await page.locator('.python-cad-viewer').getAttribute('data-session-id');
  const proposed = await readResource(page, `cad://session/${sid}/context`);
  expect(proposed.programAttempts).toHaveLength(0);
  expect(proposed.lastResult).toBeNull();
  await confirm(page);
  await expect(page.getByText('Python completed.', { exact: true })).toBeVisible();
  await expect(page.getByText('Proposed Python · Generated mesh study', { exact: true }).first()).toBeVisible();
  await expect(page.locator('pre code')).toContainText('for size in [6, 4, 3]');
  await expect(page.getByText('Synthetic mesh comparison', { exact: true })).toBeVisible();
  await expect(page.locator('img[src*="vonMisesStress"]')).toBeVisible();
  await expect(page.locator('a[href*="agent.py"]')).toBeVisible();
  const context = await readResource(page, `cad://session/${sid}/context`);
  expect(context.executionMode).toBe('generated-python');
  expect(context.programAttempts).toHaveLength(1);
  expect(context.lastResult.verifiedSolves).toHaveLength(3);
  await page.screenshot({ path: 'test-results/generated-code-ui.png', fullPage: true });
});
