import { conditionTypes, conditionSummary } from './conditions.js';

export class BoundaryPanel {
  constructor(element, { onSave, onDelete, onSelect }) {
    this.element = element;
    this.onSave = onSave;
    this.onDelete = onDelete;
    this.onSelect = onSelect;
    element.innerHTML = `
      <div class="section-heading"><h2>Boundary conditions <span id="boundary-count" class="badge">0</span></h2></div>
      <form id="boundary-form">
        <label for="boundary-type">Condition type</label>
        <select id="boundary-type">${Object.entries(conditionTypes).map(([key, type]) => `<option value="${key}">${type.label}</option>`).join('')}</select>
        <div id="boundary-vector" class="boundary-vector" hidden>
          ${['x', 'y', 'z'].map(axis => `<label for="boundary-${axis}">${axis.toUpperCase()} <span class="boundary-unit"></span><input id="boundary-${axis}" type="number" step="any" value="0" required /></label>`).join('')}
        </div>
        <div id="boundary-scalar" hidden><label for="boundary-magnitude">Pressure (MPa)</label><input id="boundary-magnitude" type="number" step="any" value="1" required /></div>
        <p id="boundary-hint" class="boundary-hint"></p>
        <div class="boundary-buttons"><button id="boundary-cancel" type="button" hidden>Cancel</button><button id="boundary-save" class="primary" type="submit">Apply to face</button></div>
      </form>
      <p id="boundary-selection-hint" class="boundary-hint">Select a face to apply a boundary condition.</p>
      <div id="boundary-list"></div>
    `;
    this.$ = id => element.querySelector(`#${id}`);
    this.$('boundary-type').onchange = () => this.updateType();
    this.$('boundary-cancel').onclick = () => this.reset();
    this.$('boundary-form').onsubmit = e => {
      e.preventDefault();
      if (!this.selected || !this.available) return;
      const type = this.$('boundary-type').value;
      const values = type === 'fixed' ? {} : type === 'pressure'
        ? { magnitude: Number(this.$('boundary-magnitude').value) }
        : Object.fromEntries(['x', 'y', 'z'].map(axis => [axis, Number(this.$(`boundary-${axis}`).value)]));
      this.onSave({ id: this.editing, faceKey: this.selected, type, values });
    };
    this.updateType();
  }

  updateType() {
    const key = this.$('boundary-type').value;
    const vector = key === 'force' || key === 'displacement';
    this.$('boundary-vector').hidden = !vector;
    this.$('boundary-scalar').hidden = key !== 'pressure';
    for (const axis of ['x', 'y', 'z']) this.$(`boundary-${axis}`).disabled = !vector || !this.selected || !this.available;
    this.$('boundary-magnitude').disabled = key !== 'pressure' || !this.selected || !this.available;
    this.element.querySelectorAll('.boundary-unit').forEach(label => { label.textContent = `(${conditionTypes[key].unit})`; });
    this.$('boundary-hint').textContent = conditionTypes[key].hint;
  }

  reset() {
    this.editing = null;
    this.$('boundary-type').value = 'fixed';
    for (const axis of ['x', 'y', 'z']) this.$(`boundary-${axis}`).value = '0';
    this.$('boundary-magnitude').value = '1';
    this.$('boundary-save').textContent = 'Apply to face';
    this.$('boundary-cancel').hidden = true;
    this.updateType();
  }

  render({ selected, conditions, faces, available }) {
    if (selected !== this.selected) { this.selected = selected; this.reset(); }
    this.available = available;
    this.$('boundary-count').textContent = conditions.length;
    this.$('boundary-selection-hint').hidden = !!selected;
    this.$('boundary-type').disabled = !selected || !available;
    this.$('boundary-save').disabled = !selected || !available;
    this.$('boundary-cancel').disabled = !available;
    this.updateType();
    this.$('boundary-list').replaceChildren();
    for (const condition of conditions) {
      const face = faces.get(condition.faceKey);
      const card = document.createElement('article');
      card.className = `boundary-card${selected === condition.faceKey ? ' active' : ''}`;
      card.style.setProperty('--condition-color', conditionTypes[condition.type].color);
      const jump = document.createElement('button');
      jump.className = 'boundary-jump';
      jump.textContent = `${conditionTypes[condition.type].label} · ${face ? `Face ${face.faceIndex}` : 'Unmapped face'}`;
      jump.title = condition.faceKey;
      jump.disabled = !available;
      jump.onclick = () => this.onSelect(condition.faceKey);
      const details = document.createElement('p');
      details.textContent = conditionSummary(condition);
      const actions = document.createElement('div');
      actions.className = 'boundary-buttons';
      const edit = document.createElement('button');
      edit.textContent = 'Edit condition'; edit.disabled = !available || !face;
      edit.onclick = () => {
        this.onSelect(condition.faceKey);
        this.editing = condition.id;
        this.$('boundary-type').value = condition.type;
        for (const axis of ['x', 'y', 'z']) this.$(`boundary-${axis}`).value = condition.values[axis] ?? 0;
        this.$('boundary-magnitude').value = condition.values.magnitude ?? 1;
        this.$('boundary-save').textContent = 'Save condition';
        this.$('boundary-cancel').hidden = false;
        this.updateType();
        this.$('boundary-type').focus();
      };
      const remove = document.createElement('button');
      remove.textContent = 'Remove condition'; remove.disabled = !available;
      remove.onclick = () => { if (confirm('Remove this boundary condition?')) this.onDelete(condition); };
      actions.append(edit, remove);
      card.append(jump, details, actions);
      this.$('boundary-list').append(card);
    }
  }
}
