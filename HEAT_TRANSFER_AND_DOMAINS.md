# Heat-transfer visuals, fluid geometry and concise onboarding

Every opened/uploaded CAD starts the existing conversation by asking:
**Is this a mechanical, heat transfer, or fluid dynamics simulation?** The prompt
is visible immediately, before the first user message. It does not require a face
click. Selectable cards provide common answers; free text remains available.
Intent is recorded by `set_simulation_intent`; a fresh
import has an independent setup. A click never answers the physics question.

## User-defined fluid domains

After selecting fluid dynamics, chat asks whether the fluid domain is already
present or needs adding. It is **not restricted to a bounding box**:

- **Existing fluid volume:** user identifies the uploaded STEP as actual fluid CAD.
- **Box enclosure:** user supplies min/max global X/Y/Z coordinates in mm.
- **Cylindrical/pipe domain:** user supplies the start-center XYZ, axis direction,
  **inner fluid radius**, and length in mm (not the wall's outside radius).
- **Other standard methods:** `custom` accepts the user's description and finite
  numeric parameters, e.g. annular passages, extracted internal regions, symmetry
  sectors, or external enclosures. A definition does not expand Fluent's currently
  supported physics/domain topology.

The user must identify the uploaded CAD's role: fluid volume, obstacle, or reference.
The agent asks for missing dimensions/clearances rather than inventing them.
`set_fluid_domain` saves the definition through guided confirmation. Then
`create_fluid_domain` constructs a **real box or cylinder** locally with OpenCascade,
subtracting closed CAD solids for the obstacle role, or creating an explicit empty
volume for reference role. The original CAD and annotations remain untouched.
The new derived model starts with empty conditions and face identities bound to its
new CAD hash. It is shown as a transparent fluid enclosure with opaque obstacle walls;
the generated STEP and geometric check report are downloadable in chat.

Construction checks containment, positive obstacle clearance, valid watertight solids,
one connected fluid region, and volume before/after STEP export. Invalid Boolean cuts,
touching/outside obstacles, sealed disconnected cavities, or worker timeouts never
replace the active model. The local CAD subprocess has a 120-second deadline.
Custom internal-passage extraction/capping and other unimplemented techniques still
require prepared CAD. A saved definition alone is never sent to Fluent as fluid CAD.

When the user asks the agent to choose a non-contact clearance, `suggest_fluid_domain`
can propose `max(1 mm, 2% of the largest CAD span)` while preserving explicitly fixed
axes (e.g. keep Y −50…50). This is read-only until confirmed; the agent must not keep
asking for an arbitrary number after that choice has been delegated. It establishes
geometric separation, **not** adequate CFD domain size or mesh/domain independence.

## Short, choice-first chat

The assistant asks one short question at a time. Single-select cards use radio inputs;
multi-select questions use checkboxes. **More context** disclosures hold optional
explanation, exact tool arguments and diagnostics. Core dimensions, units and the
operation remain visible on the confirmation card. The active proposal is not printed
twice. Code remains separately expandable and reviewable before execution.

Choice submissions are bound to the session, current model, current question token,
and (for state-dependent questions) the setup fingerprint. Old/foreign choices and
invalid combinations are rejected; the server supplies the authoritative answer text.
Request IDs deduplicate retries. Generic selection options cannot stand in for the
exact confirmation button. Keyboard navigation and free-text corrections remain usable.

## Thermal face annotations

| Kind | Fields | Units / convention | Graphic |
| --- | --- | --- | --- |
| `temperature` | `temperature` | °C, at least −273.15 | Thermometer bulb/stem |
| `heat_flux` | `magnitude` | W/m²; positive inward, negative outward, zero allowed | Normal arrows; zero-flux barrier |
| `convection` | `coefficient`, `ambient_temperature` | Positive W/(m² K), ambient °C | Wavy film-exchange symbol |
| `radiation` | `emissivity`, `ambient_temperature` | ε from 0 to 1, surroundings °C | Radiative wave rays |
| `adiabatic` | none | Zero normal heat flux | Hatched insulation barrier |

Each includes full-face tint, correctly unit-labelled conditions, session-only
proposed graphics, confirmation, persistence, and annotation JSON round-trips.
Convection/radiation symbols do not assert a net direction before surface temperature
is known. Prescribed temperature/insulation cannot conflict with another thermal
condition on the same face. Thermal and structural/fluid annotation families remain
separate; insulation is never converted into a structural fixed support.

Generated **PyMechanical** thermal code must explicitly implement these annotations,
choose steady/transient physics and valid material properties, and use verified
original-face selections. The structural preset/export reconstruction cannot silently
apply them as structural loads. This feature does not add Fluent heat transfer or CHT;
the current Fluent worker remains isothermal. Mechanical and Fluent licensing has
been confirmed working by the operator; it is not a current blocker.

## Checks

`tests/python/test_domain_geometry.py` runs real OpenCascade box/cylinder cuts,
including rotated cylinders, contact/containment failures, disconnected cavities,
timeouts, source preservation and cache integrity. `test_chat_choices.py` verifies
choice-token/session binding, multi-select, deduplication and approval separation.
The Studio browser suite also builds actual fluid CAD through the selection cards
and verifies its STEP download and transparent rendering (no solver license used).

`tests/python/test_thermal_domain.py` checks onboarding, domain definitions, unit
validation, proposal safety, persistence, conflicts and solver-input separation.
`npm test` checks glyph geometry, finite coordinates, signed heat-flux arrows and
unit labels. Studio browser tests cover the visible upload prompt, pipe definitions,
all five thermal graphics and refresh persistence using explicit synthetic fixtures.
