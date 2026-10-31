# Python endpoint references for native ports

## Supported operation: GET /api/v2/roll/bootstrap

`roll-bootstrap-v2.openapi.json` is the frozen operation snapshot and full
referenced component closure captured from `frontend/src/generated/openapi.json`
immediately before the Python v2 handler was deleted. The operation is served
by native Rust ingress only (`api/native_roll.rs` → `native/roll-service`, routed
from `vercel.json`). `app/schemas/roll_v2.py` and
`tests/test_roll_v2_frozen_contract.py` keep the frozen Python DTO aligned with
this contract.

To compare an independently generated Rust OpenAPI operation:

```sh
python scripts/rust_endpoint_oracle.py check \
  --schema /tmp/rust-generated-openapi.json \
  --contract native/contracts/roll-bootstrap-v2.openapi.json \
  --path /api/v2/roll/bootstrap
```

The comparison includes the full referenced component closure, not only the
top-level response. It must receive actual native-generated output. The frozen
Python file alone does not establish native parity, runtime behavior, or a
production cutover.

## Retired operation: GET /api/v1/roll/bootstrap

`roll-bootstrap-v1.openapi.json` is the historical v1 operation snapshot from
production commit `cdaa74f` (#4350/#4371). It includes nested models, security
schemes and query defaults. Arrays retain their original ordering.

The v1 and legacy bootstrap paths are retired, not ported. This snapshot is
retained only as behavioral evidence for fields the live Roll UI used to see.
The real normal consumer is `frontend/src/services/rollBootstrapApi.ts`, and
recovery uses `frontend/src/services/protectedRollMutationApi.ts`; both now call
the v2 operation.

This directory does not change ingress or resurrect a Python handler.
