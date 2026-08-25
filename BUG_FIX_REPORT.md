# BUG FIX REPORT

- Updated: 2026-08-25T16:10:41.520418+00:00
- BUG-001 P1: frontend build failed (vite 8 rolldown native binding missing on
  macOS x64). Fix: downgraded vite to 6.4.3 and @vitejs/plugin-react to 4.3.4;
  installed @testing-library/dom; vitest uses Node 22. Retest: build and tests
  pass.
