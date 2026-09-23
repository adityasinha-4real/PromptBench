// eslint-config-next 16 ships flat config, so its pieces are imported
// directly. Wrapping them in FlatCompat (needed for v15's legacy configs)
// throws "Converting circular structure to JSON".
import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';
import nextTypescript from 'eslint-config-next/typescript';

const config = [
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    ignores: ['.next/**', 'node_modules/**', 'next-env.d.ts'],
  },
  {
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-explicit-any': 'error',

      // New in eslint-plugin-react-hooks 7 (arrived with Next 16). They flag
      // 10 existing sites, including useAsync and the SSE progress hook.
      // Reworking those is a refactor with its own regression risk, not part
      // of a dependency bump, so they warn until that is done deliberately.
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/refs': 'warn',
    },
  },
];

export default config;
