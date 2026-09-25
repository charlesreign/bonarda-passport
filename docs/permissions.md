# Role permission matrix

Generated from `backend/app/modules/identity/permissions.py`.
Do not edit by hand; from `backend/` run:

    python -m app.modules.identity.permissions ../docs/permissions.md

`worker:read` is further limited per worker by the visibility policy
(spec §7.1).

| Permission | pm | people_ops | finance | worker | admin |
|---|---|---|---|---|---|
| `worker:read_self` |  |  |  | ✓ |  |
| `worker:update_self` |  |  |  | ✓ |  |
| `worker:read` | ✓ | ✓ |  |  | ✓ |
| `worker:invite` | ✓ |  |  |  |  |
| `dispute:file` |  |  |  | ✓ |  |
| `dispute:resolve` |  | ✓ |  |  |  |
| `project:manage` | ✓ | ✓ |  |  |  |
| `project:staff_assign` |  | ✓ |  |  |  |
| `roster:search` | ✓ |  |  |  |  |
| `engagement:create` | ✓ |  |  |  |  |
| `engagement:reactivate` | ✓ |  |  |  |  |
| `engagement:read_billing` |  |  | ✓ |  |  |
| `feedback:submit` | ✓ |  |  |  |  |
| `first_shot:review` | ✓ |  |  |  |  |
| `access_grant:manage` |  | ✓ |  |  |  |
| `policy:propose` |  | ✓ |  |  |  |
| `policy:activate` |  | ✓ |  |  |  |
| `standing:override` |  | ✓ |  |  |  |
| `governance:read` |  | ✓ |  |  | ✓ |
| `audit:read` |  | ✓ |  |  | ✓ |
| `skill:manage` |  | ✓ |  |  |  |
| `worker:erase` |  | ✓ |  |  |  |
