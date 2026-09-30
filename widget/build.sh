#!/usr/bin/env bash
# build.sh — bundle every widget/<Component>.tsx into widget/dist/<Component>.js
#
# Usage:
#   cd widget && npm install   # one-time
#   cd widget && ./build.sh    # bundles everything
#
# Run from anywhere; resolves paths relative to its own location.
#
# Bundle invariants (verified after build):
#   - --alias rewrites bare `react` and `react/jsx-runtime` to host-served
#     shim URLs (canonical for NousViz core v0.9.4.7+, B156 resolution).
#   - --external prevents esbuild from trying to resolve the rewritten URL
#     on disk. Both flags required together — see appendix-gotchas.md G-3.
#   - The output JS has no `react` imports of its own and no React internals.
#     Hooks resolve through the host's single React instance.

set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d node_modules ]; then
  echo "node_modules missing — run 'npm install' inside widget/ first." >&2
  exit 1
fi

mkdir -p dist

shopt -s nullglob
# Pick up every .tsx with a capital-letter prefix (component convention).
components=( [A-Z]*.tsx )
shopt -u nullglob

if [ ${#components[@]} -eq 0 ]; then
  echo "No <Component>.tsx files found in $(pwd) — nothing to build." >&2
  exit 0
fi

echo "Building ${#components[@]} widget(s)..."
for src in "${components[@]}"; do
  name="${src%.tsx}"
  echo "  $src -> dist/$name.js"
  ./node_modules/.bin/esbuild "$src" \
    --bundle \
    --format=esm \
    --target=es2020 \
    --jsx=automatic \
    --alias:react=/api/widget-runtime/react.js \
    --alias:react/jsx-runtime=/api/widget-runtime/react-jsx-runtime.js \
    --external:/api/widget-runtime/react.js \
    --external:/api/widget-runtime/react-jsx-runtime.js \
    --outfile="dist/$name.js" \
    --log-level=warning
done
echo "Done."
