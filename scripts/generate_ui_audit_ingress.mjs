#!/usr/bin/env node
/** Generate the UI audit's HTTP-method-aware nginx ingress from production routing.
 *
 * Every API request is owned by native Rust after the Python API teardown.
 * Never maintain a separate hand-written API allowlist here: it drifts during
 * the cutover and turns real Rust endpoints into misleading 404s.
 */
import {readFileSync, writeFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

const RUST = new Set(['/api/native_roll.rs', '/api/native_issue.rs']);
// main's bot-owned vercel.json can still carry stale Python exceptions until
// regenerate-routes.yml lands; they must be exercised as Rust 404s now.
const RETIRED_PYTHON = '/api/index.py';
const FALLBACK = '/api(?:/.*)?';
const ALL_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'];

export function renderAuditIngress(config) {
  if (!Array.isArray(config?.routes)) throw new Error('vercel.json needs routes');
  const expressions = [];
  let hasRustFallback = false;
  let nativeOperations = 0;
  for (const route of config.routes) {
    if (route.src === FALLBACK) {
      if (!RUST.has(route.dest)) throw new Error('API fallback must use Rust');
      hasRustFallback = true;
      continue;
    }
    if (!route.src?.startsWith('/api/') && !route.src?.startsWith('^/api/')) continue;
    if (!RUST.has(route.dest) && route.dest !== RETIRED_PYTHON) {
      throw new Error(`Unknown API destination ${route.dest} for ${route.src}`);
    }
    if (/[\r\n;]/.test(route.src)) throw new Error('Unsafe nginx ingress expression');
    const methods = route.methods ?? ALL_METHODS;
    if (!Array.isArray(methods) || methods.length === 0 ||
        methods.some(method => !ALL_METHODS.includes(method))) {
      throw new Error(`Invalid HTTP methods for ${route.src}`);
    }
    const source = route.src.replace(/^\^/, '').replace(/\$$/, '');
    const expression = `~^(?:${methods.join('|')}):(?:${source})$`;
    nativeOperations += 1;
    expressions.push(`    ${expression} rust;`);
  }
  if (!hasRustFallback || !nativeOperations) {
    throw new Error('Audit requires explicit native Rust routes and Rust default');
  }
  return `# Generated from vercel.json by scripts/generate_ui_audit_ingress.mjs.
# Production ingress order is authoritative. The default API 404 is Rust.
map "$request_method:$uri" $audit_api_runtime {
    default rust;
${expressions.join('\n')}
}

map $audit_api_runtime $audit_api_upstream {
    rust http://127.0.0.1:8010;
}

server {
    listen 8080;
    server_name _;
    client_max_body_size 16m;

    location ^~ /api/ {
        proxy_pass $audit_api_upstream;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        add_header X-ComicPile-API-Runtime $audit_api_runtime always;
    }
    location = /api {
        proxy_pass $audit_api_upstream;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        add_header X-ComicPile-API-Runtime $audit_api_runtime always;
    }
    location = /health {
        proxy_pass http://127.0.0.1:8010/health;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }
    location / {
        root /usr/share/nginx/html;
        try_files $uri /index.html;
    }
}
`;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [, , configFile, outputFile] = process.argv;
  if (!configFile || !outputFile) {
    throw new Error('Usage: node generate_ui_audit_ingress.mjs vercel.json output.conf');
  }
  writeFileSync(outputFile, renderAuditIngress(JSON.parse(readFileSync(configFile, 'utf8'))));
  console.log(`Generated Rust-default UI audit ingress: ${outputFile}`);
}
