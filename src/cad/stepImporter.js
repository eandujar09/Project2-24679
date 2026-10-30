import importerUrl from 'occt-import-js/dist/occt-import-js.js?url';
import wasmUrl from 'occt-import-js/dist/occt-import-js.wasm?url';

export function importStep(buffer, signal) {
  // A dedicated classic worker isolates synchronous OpenCascade work from the UI.
  const source = `
    self.onmessage = async ({data}) => {
      try {
        importScripts(data.script);
        const occt = await occtimportjs({ locateFile: () => data.wasm });
        const result = occt.ReadStepFile(new Uint8Array(data.buffer), {
          linearUnit: 'millimeter', linearDeflectionType: 'bounding_box_ratio',
          linearDeflection: 0.001, angularDeflection: 0.5
        });
        if (!result.success || !result.meshes?.length) throw new Error('No geometry found. Check that this is a valid, supported STEP file.');
        self.postMessage({result});
      } catch (error) { self.postMessage({error: error.message || String(error)}); }
    };
  `;
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }));
    const worker = new Worker(url);
    const finish = (error, result) => {
      worker.terminate(); URL.revokeObjectURL(url);
      signal?.removeEventListener('abort', abort);
      error ? reject(error) : resolve(result);
    };
    const abort = () => finish(new DOMException('Import cancelled', 'AbortError'));
    if (signal?.aborted) { abort(); return; }
    signal?.addEventListener('abort', abort, { once: true });
    worker.onmessage = ({ data }) => finish(data.error ? new Error(data.error) : null, data.result);
    worker.onerror = () => finish(new Error('STEP importer failed. Reload and try a smaller file; check that WebAssembly assets are available.'));
    worker.postMessage({ buffer, script: new URL(importerUrl, location.href).href, wasm: new URL(wasmUrl, location.href).href }, [buffer]);
  });
}

export async function modelHash(buffer) {
  const hash = await crypto.subtle.digest('SHA-256', buffer);
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
}
