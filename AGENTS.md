# Simulation MCP integration

For Fluent work, use the registered official `ansys-fluent` MCP server, matching
the workspace's `ansys-mechanical` MCP integration. See `FLUENT_MCP.md` for setup
and the distinction between coding-agent tooling and Studio worker execution.

- Check MCP session status before connecting; do not interfere with another job.
- Discover unfamiliar APIs and inspect live properties/allowed values rather than
  guessing names. Offline catalogs may differ from the installed Fluent release.
- Validate new code through MCP before executing it. Offline parse success does
  not validate the live API, geometry, physics, or engineering assumptions.
- Verify state after a change, especially import units, regions and boundary names.
- Keep execution confirmation, model identity, face mapping, cell caps, convergence,
  and uncertain-job recovery safeguards. Do not alter scripts to bypass a worker bug.
- Mechanical remains independent. Do not upgrade its environment or the Fluent
  worker environment when installing the separate Fluent MCP dependencies.

Studio's `review_fluent_workflow` supplies a read-only setup review and the proven
authored native-STEP example. Adapt the example to approved inputs; never inject
its water/laminar/numerical assumptions as hidden defaults. Preserve per-face CAD
zones in both import and surface generation and keep strict geometric mapping.

Native screenshots use the optional isolated `fluent-post` MCP adapter through
`fluent.postprocessing`, after a verified converged result or via the typed
`render_fluent_results` action. It never iterates or changes the physical setup.
Do not rerun a solve because graphics failed; unknown jobs remain recovery-only.
Distinguish native contours from ctx.capture Matplotlib extraction plots and from
internal fluid slices. See `fluent/WORKFLOW_IMPROVEMENTS.md`.
