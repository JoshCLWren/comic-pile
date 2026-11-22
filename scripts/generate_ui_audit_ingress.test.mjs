import assert from 'node:assert/strict';
import {test} from 'node:test';
import {renderAuditIngress} from './generate_ui_audit_ingress.mjs';

test('audit ingress preserves production method/path routing and native priority', () => {
  const config = {routes: [
    {src: '^/api/v1/auth/login$', methods: ['POST'], dest: '/api/native_roll.rs'},
    {src: '^/api/v1/threads/[^/]+/restore$', methods: ['POST', 'OPTIONS'], dest: '/api/native_roll.rs'},
    {src: '^/api/v1/threads/[^/]+/issues$', methods: ['GET'], dest: '/api/native_issue.rs'},
    {src: '/api(?:/.*)?', dest: '/api/native_roll.rs'},
  ]};
  const nginx = renderAuditIngress(config);
  assert.match(nginx, /default rust;/);
  assert.match(nginx, /~\^\(\?:POST\):\(\?:\/api\/v1\/auth\/login\)\$ rust;/);
  assert.match(nginx, /~\^\(\?:POST\|OPTIONS\):\(\?:\/api\/v1\/threads\/\[\^\/\]\+\/restore\)\$ rust;/);
  assert(nginx.indexOf('auth/login') < nginx.indexOf('/restore'));
  assert.match(nginx, /proxy_pass \$audit_api_upstream;/);
  assert.match(nginx, /add_header X-ComicPile-API-Runtime \$audit_api_runtime always;/);
  assert.match(nginx, /location = \/health/);
  assert.match(nginx, /root \/usr\/share\/nginx\/html;/);
});

test('stale pre-regeneration Python exceptions are audited as Rust', () => {
  const nginx = renderAuditIngress({routes: [
    {src: '^/api/v1/legacy$', methods: ['GET'], dest: '/api/index.py'},
    {src: '/api(?:/.*)?', dest: '/api/native_roll.rs'},
  ]});
  assert.match(nginx, /~\^\(\?:GET\):\(\?:\/api\/v1\/legacy\)\$ rust;/);
  assert.doesNotMatch(nginx, /python/);
});

test('audit ingress rejects a Python catch-all or unknown API runtime', () => {
  assert.throws(() => renderAuditIngress({routes: [
    {src: '^/api/v2/ping$', methods: ['GET'], dest: '/api/native_roll.rs'},
    {src: '/api(?:/.*)?', dest: '/api/index.py'},
  ]}), /fallback must use Rust/);
  assert.throws(() => renderAuditIngress({routes: [
    {src: '^/api/v2/ping$', methods: ['GET'], dest: '/api/unknown.py'},
    {src: '/api(?:/.*)?', dest: '/api/native_roll.rs'},
  ]}), /Unknown API destination/);
});
