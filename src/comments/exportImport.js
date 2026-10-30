import { validateConditions } from '../boundaries/conditions.js';

export function validateAnnotations(data, modelId) {
  if (!data || ![1, 2].includes(data.schemaVersion) || !Array.isArray(data.comments) || typeof data.filename !== 'string' ||
      (data.schemaVersion === 2 && !Array.isArray(data.boundaryConditions))) {
    throw new Error('Invalid annotation file or unsupported schema version.');
  }
  if (data.modelId !== modelId) throw new Error('These annotations belong to a different STEP file (SHA-256 mismatch). Open the exact original model to import them.');
  const ids = new Set();
  return data.comments.map(comment => {
    if (!comment || typeof comment.id !== 'string' || !comment.id.trim() || ids.has(comment.id) ||
        comment.modelId !== modelId || typeof comment.faceKey !== 'string' || !comment.faceKey.trim() ||
        typeof comment.text !== 'string' || !comment.text.trim() ||
        typeof comment.createdAt !== 'string' || !Number.isFinite(Date.parse(comment.createdAt)) ||
        typeof comment.updatedAt !== 'string' || !Number.isFinite(Date.parse(comment.updatedAt))) {
      throw new Error('Invalid comment fields, dates, or duplicate IDs in annotation file.');
    }
    if (comment.anchor !== undefined && (!Array.isArray(comment.anchor) || comment.anchor.length !== 3 || !comment.anchor.every(Number.isFinite))) {
      throw new Error('Invalid comment anchor.');
    }
    ids.add(comment.id);
    return { id: comment.id, modelId, faceKey: comment.faceKey, text: comment.text.trim(), createdAt: comment.createdAt, updatedAt: comment.updatedAt, ...(comment.anchor ? { anchor: comment.anchor } : {}) };
  });
}

export function validateProjectAnnotations(data, modelId) {
  const comments = validateAnnotations(data, modelId);
  const boundaryConditions = validateConditions(data.schemaVersion === 2 ? data.boundaryConditions : [], modelId);
  return { comments, boundaryConditions };
}

export function exportAnnotations(model, comments, boundaryConditions = []) {
  const data = { schemaVersion: 2, modelId: model.id, filename: model.filename, comments, boundaryConditions };
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `${model.filename}.comments.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
