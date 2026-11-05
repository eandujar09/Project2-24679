import { defineConfig } from 'vite';
import path from 'node:path';
import tailwindcss from 'tailwindcss';
import autoprefixer from 'autoprefixer';

export default defineConfig({
  root: path.resolve('src/studio'),
  publicDir: false,
  esbuild: { jsx: 'automatic' },
  css: { postcss: { plugins: [tailwindcss('./src/studio/zoo-tailwind.cjs'), autoprefixer()] } },
  build: { outDir: path.resolve('gradio_app/studio_static'), emptyOutDir: true, assetsDir: 'studio-assets' },
});
