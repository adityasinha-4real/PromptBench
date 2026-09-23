// .mts because Vite 8 loads configs natively: ESM syntax in a file it treats
// as CommonJS warns, and that loader becomes the default in a later major.
import path from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, '.') },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./test/setup.ts'],
    include: ['test/**/*.test.{ts,tsx}'],
    css: false,
    restoreMocks: true,
  },
});
