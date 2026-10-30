import type { NextConfig } from 'next';
const config: NextConfig = {
  distDir: process.env.PAPER_BUILD_DIR || '.next',
  outputFileTracingExcludes: { '/*': ['./.venv/**', './output/**', './.paper-runs/**', './.env*'] },
  serverExternalPackages: ['wink-nlp', 'wink-eng-lite-web-model'],
};
export default config;
