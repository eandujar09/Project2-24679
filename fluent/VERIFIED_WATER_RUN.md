# Verified saved-water run

Run directory: `gradio-data/exports/simulations/20261112T042420Z-host-controlled-2233a3ff25`.
This is a real Fluent 261 solve of the saved derived fluid domain, not a synthetic
fixture. It ran through the same 900-second/resource-checked worker on the host,
after an interrupted OpenCode-transport attempt was positively identified and
recovered as failed. It was not attached as a new result to Studio's in-memory
conversation. The authenticated Gradio file endpoint serves the result archive.

## Measured verification

- Source CAD SHA-256: `fb06de6f1ce8e89e9836ee3d52b1691ab55f6c2c10ae8d634d14f1e88855aa64`.
- All **18 original CAD faces** geometrically mapped; no guessed IDs or relaxed
  mapping tolerances. One fluid cell zone, no solid cell zones, **25,685 cells**.
- **929 iterations** of the approved 1,000 maximum.
- Final scaled residuals: continuity **9.921335634991214e-6**, x velocity
  **3.108867282580742e-8**, y velocity **6.868572123480924e-8**, z velocity
  **2.223590280792152e-8**. All passed the unchanged **1e-5** criterion.
- Relative mass imbalance **1.7737082582379956e-7**, below the unchanged **0.001**.
- Actual native case/data, pressure/velocity surface PNGs and CSVs, exact source,
  request snapshot, face mapping, residual history and logs are in `simulation.zip`.
- Boundary-surface extrema: pressure **-1746.5374755859375 to 4633.86767578125 Pa
  gauge**; velocity magnitude **0 to 3.045135736465454 m/s**. These are boundary
  samples, not asserted volume-wide extrema.

## What worked

1. Reimport the **unchanged native STEP** instead of remeshing only its STL proxy.
   Preserve CAD curvature and set `OneZonePer: face` in **both import and surface
   generation** `CadImportOptions`. Without the latter, CAD faces were merged.
2. Keep the **4 mm global maximum**, add **6-degree curvature resolution**, and
   use polyhedral filling with maximum length 4 mm, growth rate 1.4 and polyhedral
   feature angle 5 degrees. Region/face checks and the 32,000-cell cap stay enabled.
3. Use Fluent 261's canonical scalar-material option **`value`** for the agreed
   constant density 1000 kg/m³ and viscosity 0.001 Pa s. The worker readback now
   accepts `value`/`constant` but still rejects expression/UDF options or wrong values.
4. Retain the coupled, second-order solution method. Apply explicit pressure/
   momentum relaxation **0.2/0.5**, high-order-term relaxation **enabled at 0.25**,
   and automatic pseudo-time scale factor **0.1**. Baseline coupled settings, tighter
   linear-solver tolerance alone, and pseudo-time scaling alone did not meet the
   agreed residual criterion. No threshold was loosened to obtain success.

Readable authored example: [`examples/fluent-native-steady-water.py`](../examples/fluent-native-steady-water.py).
The exact executed source is `results/agent.py` in the run archive; SHA-256:
`c064d2da7fac2f0fdc1b05f32f8398479698582c62d356b418625840a77a6765`.
The example is not injected by the worker or a blanket default for other models.

Saved geometry, the 4 mm target, all 18 conditions, water properties and physical
assumptions were unchanged. Numerical convergence on this one mesh does **not**
establish mesh/domain independence or physical appropriateness of the user's
steady laminar assumption at the previously estimated high Reynolds number.
