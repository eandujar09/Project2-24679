import { openDB } from 'idb';

const database = openDB('step-face-comments', 2, {
  upgrade(db, oldVersion) {
    if (oldVersion < 1) {
      db.createObjectStore('models', { keyPath: 'id' });
      const comments = db.createObjectStore('comments', { keyPath: 'id' });
      comments.createIndex('modelId', 'modelId');
      comments.createIndex('modelFace', ['modelId', 'faceKey']);
      db.createObjectStore('settings');
    }
    if (oldVersion < 2) {
      const boundaries = db.createObjectStore('boundaryConditions', { keyPath: 'id' });
      boundaries.createIndex('modelId', 'modelId');
      boundaries.createIndex('modelFace', ['modelId', 'faceKey']);
    }
  },
});
// Callers still receive storage failures; avoid an unhandled startup rejection.
database.catch(() => {});

export const store = {
  async saveModel(model) {
    const db = await database;
    const tx = db.transaction(['models', 'settings'], 'readwrite');
    await tx.objectStore('models').put(model);
    await tx.objectStore('settings').put(model.id, 'lastModel');
    await tx.done;
  },
  async lastModel() {
    const db = await database;
    const id = await db.get('settings', 'lastModel');
    return id ? db.get('models', id) : null;
  },
  async comments(modelId) { return (await database).getAllFromIndex('comments', 'modelId', modelId); },
  async put(comment) { await (await database).put('comments', comment); },
  async delete(id) { await (await database).delete('comments', id); },
  async boundaries(modelId) { return (await database).getAllFromIndex('boundaryConditions', 'modelId', modelId); },
  async putBoundary(condition) { await (await database).put('boundaryConditions', condition); },
  async deleteBoundary(id) { await (await database).delete('boundaryConditions', id); },
  async merge(comments, modelId, boundaryConditions = []) {
    const db = await database;
    const tx = db.transaction(['comments', 'boundaryConditions'], 'readwrite');
    // Observe transaction rejection even when an explicit conflict aborts it.
    tx.done.catch(() => {});
    for (const [name, records] of [['comments', comments], ['boundaryConditions', boundaryConditions]]) {
      const target = tx.objectStore(name);
      for (const record of records) {
        const existing = await target.get(record.id);
        if (existing && existing.modelId !== modelId) {
          tx.abort();
          throw new Error('An annotation ID belongs to another model. Import was cancelled.');
        }
        await target.put(record);
      }
    }
    await tx.done;
  },
};
