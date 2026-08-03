# Issue Kanban Notes

## 2026-08-03

- Analytics was retired from the primary application workflow in #611 pending a separately planned redesign. The navigation entry is removed and direct `/analytics` visits redirect to `/`; authenticated users then reach the Roll page, while unauthenticated users follow normal protected-route handling. The existing backend analytics API remains available and unchanged.
