import type { ApiClient } from './api'

/**
 * HttpClient is an abstraction over the outgoing HTTP transport used by the
 * service layer.  The implementation is slightly looser than the concrete
 * `ApiClient` type defined in `api.ts` but satisfies both the existing and
 * refactored service modules.
 */
export type HttpClient = ApiClient
