import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';

let fixture;
let simulationFixture;
test.beforeAll(() => {
  const directory = path.resolve('test-results/gradio-fixtures');
  mkdirSync(directory, { recursive: true });
  fixture = path.join(directory, 'cylinder.step');
  simulationFixture = path.join(directory, 'simulation-cylinder.step');
  const python = process.platform === 'win32' ? '.venv-gradio/Scripts/python.exe' : '.venv-gradio/bin/python';
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

test('Python geometry is pickable, synchronizes with Gradio, and shows boundary graphics', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') console.error(message.text()); });
  await page.goto('/');
  await expect(page.getByText('Open a STEP model to begin.', { exact: true })).toBeVisible({ timeout: 15000 });
  await page.locator('input[type=file]').first().setInputFiles(fixture);
  await expect(page.locator('.cad-status')).toContainText('3 CAD faces', { timeout: 30000 });
  const canvas = page.locator('#python-cad-preview canvas');
  await expect(canvas).toBeVisible();
  await canvas.evaluate(node => { node.dataset.instance = 'original-canvas'; });
  const box = await canvas.boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page.getByRole('combobox', { name: 'Select whole CAD face' })).toHaveValue(/Face \d/);
  await expect(page.getByText('python-ocp-v1:face:1', { exact: false }).first()).toBeVisible();
  await page.getByLabel('Comment text', { exact: true }).fill('Picked in the reused viewer');
  await page.getByRole('button', { name: 'Save comment', exact: true }).click();
  await expect(page.getByLabel('Project status', { exact: true })).toHaveValue(/1 comments/);
  await expect(canvas).toBeVisible();
  await expect(canvas).toHaveAttribute('data-instance', 'original-canvas');
  await page.getByRole('tab', { name: 'Boundary conditions', exact: true }).click();
  await page.getByRole('button', { name: 'Apply to face', exact: true }).click();
  await expect(page.locator('.boundary-label')).toContainText('Fixed support');
  await expect(page.getByLabel('Project status', { exact: true })).toHaveValue(/1 conditions/);
  await page.getByRole('button', { name: 'Clear face', exact: true }).first().click();
  await expect(page.getByRole('combobox', { name: 'Select whole CAD face' })).toHaveValue('');
  const picker = page.getByRole('combobox', { name: 'Select whole CAD face' });
  await picker.click();
  await page.getByRole('option', { name: /Face 2 ·/ }).click();
  await expect(picker).toHaveValue(/Face 2/);
  await expect(canvas).toHaveAttribute('data-instance', 'original-canvas');
  await page.getByRole('button', { name: 'Clear face', exact: true }).first().click();
  await expect(picker).toHaveValue('');
  // Orbit drags must not create a face selection.
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 65, box.y + box.height / 2 + 30, { steps: 12 });
  await page.mouse.up();
  await expect(page.getByRole('combobox', { name: 'Select whole CAD face' })).toHaveValue('');
  expect(errors).toEqual([]);
});

test('Mechanical solve displays actual stress and deformation contours', async ({ page }) => {
  test.skip(!process.env.MECHANICAL_TEST_PYTHON, 'Opt-in licensed Mechanical test');
  test.setTimeout(240000);
  await page.goto('/');
  await page.locator('input[type=file]').first().setInputFiles(simulationFixture);
  await expect(page.locator('.cad-status')).toContainText('3 CAD faces', { timeout: 30000 });
  const modelId = createHash('sha256').update(readFileSync(simulationFixture)).digest('hex');
  const timestamp = new Date().toISOString();
  const annotation = (id, face, type, values) => ({
    id, modelId, faceKey: `python-ocp-v1:face:${face}`, type, values,
    createdAt: timestamp, updatedAt: timestamp,
  });
  const annotations = {
    schemaVersion: 2, modelId, filename: 'cylinder.step', comments: [],
    boundaryConditions: [annotation('base', 3, 'fixed', {}), annotation('tip', 2, 'force', { x: 0, y: 0, z: 1000 })],
  };
  await page.locator('input[type=file]').nth(1).setInputFiles({
    name: 'annotations.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(annotations)),
  });
  await expect(page.getByLabel('Project status', { exact: true })).toHaveValue(/2 conditions/);
  await page.getByText('Ansys Mechanical · deterministic static structural simulation', { exact: true }).click();
  await page.getByLabel('Mechanical Python executable', { exact: true }).fill(process.env.MECHANICAL_TEST_PYTHON);
  await page.getByLabel('I confirm Structural Steel and the single-solid, small-deformation assumptions for this simulation', { exact: true }).check();
  await page.getByRole('button', { name: 'Run simulation in Mechanical', exact: true }).click();
  await expect(page.getByText(/^Simulation (succeeded|failed)\.$/)).toBeVisible({ timeout: 180000 });
  await expect(page.getByText('Simulation succeeded.', { exact: true })).toBeVisible();
  await expect(page.locator('img[src*="totalDeformation"]')).toBeVisible();
  await expect(page.locator('img[src*="vonMisesStress"]')).toBeVisible();
  await expect(page.getByRole('cell', { name: 'simulation.zip', exact: true })).toBeVisible();
});
