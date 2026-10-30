import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    outDir: 'gradio_app/static',
    emptyOutDir: true,
    lib: { entry: 'src/gradio/bridge.js', formats: ['es'], fileName: () => 'viewer.js', cssFileName: 'gradio' },
  },
});
