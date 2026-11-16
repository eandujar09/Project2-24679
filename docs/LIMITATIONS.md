# Scope, limits and next work

## Verified prototype scope

- STEP/STP input, original-face selection, shared state, guided previews and approval.
- Agent-authored PyMechanical and PyFluent, with fresh job sessions and saved source/artifacts.
- Mechanical bracket reference study; Fluent steady-water run with geometric face correspondence and numerical checks.
- Thermal annotations and graphics; box/cylinder fluid-domain construction with OpenCascade checks.

## Current boundaries

| Area | Limit |
| --- | --- |
| CAD | STEP/STP only. Face splits, merges, coincident/ambiguous geometry or insufficient sampling can fail mapping. Finite sampled correspondence is not a topology proof. |
| Mechanical | Generated code must choose valid physics/materials/settings for installed 261 APIs. The separate legacy preset is single-solid Structural Steel, linear static, small deformation. Its restrictions do not define every generated-code capability. |
| Resources | Mechanical: one CPU, no GPU, 15 minutes, 32,000 nodes/elements per solve. Fluent: one CPU, 15 minutes, 32,000 cells before iteration, 2,000 requested iterations per job. These are not peak meshing-memory guarantees. |
| Fluent | Checked helper supports steady flow in one fluid cell zone and no solid zones. No automatic FSI, transient stepping or multi-region CHT. Physics suitability and mesh/domain independence still need evaluation. |
| Thermal | Conditions/previews/units are implemented. Generated Mechanical code must explicitly apply them with suitable analysis/material data. The structural preset cannot silently reconstruct thermal physics. No independently verified thermal result is supplied here. |
| Domain creation | Real box/cylinder creation and closed-obstacle subtraction; unsupported custom extraction/capping needs separately prepared CAD. Suggested clearance only establishes geometric separation. |
| Model behavior | Outputs vary; essential questions, API errors and step limits can interrupt a demo. An available model API does not guarantee a correct engineering interpretation. |
| Visual tools | Require Visual assistance on and an open responsive browser. Screen pixels map through a captured camera; hidden faces cannot be selected from a visible pixel. |
| Native Fluent plots | Optional private renderer dependency. Boundary-surface contours, not internal slices; no-slip wall velocity is zero. Graphics failures are distinct from convergence failures. |
| Exports | Native files depend on a matching setup/job. A `.mechdat` alone is not a promise that all solver result files are included. |
| Deployment | Private VPN and shared login, not multi-tenant production hosting. In-memory chat resets on restart. Model/service/solver availability is external to this repo. |
| Execution | AST/source checks are misuse guards, not an operating-system sandbox. Worker code runs with the configured account's privileges. Direct MCP controllers are trusted and need their own approval flow. |

## Planned work

Broaden independently checked geometry/physics benchmarks; measure agent success and recovery rates; improve guided ambiguity handling; evaluate mesh/domain independence; extend domain preparation and verified solver scopes; add coupled workflows and internal fluid slices; strengthen deployment/version automation and account isolation.

The key uncertainty is whether the chosen setup represents the intended physical system. Successful code, successful meshing and numerical convergence are separate checks; none alone establishes that answer.
