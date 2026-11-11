import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';

// base './' keeps the built app usable from any sub-path (e.g. GitHub Pages).
export default defineConfig({
  base: './',
  plugins: [react()],
});
