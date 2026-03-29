## Failing CI Checks
- Build Docker Image: real bug - missing CacheContext module causing frontend build failure
- Frontend Lint + Typecheck: real bug - TypeScript errors due to incompatible pagination implementation

## Acceptance Criteria to Fix
1. Create missing `frontend/src/contexts/CacheContext.tsx` file or fix import path in `frontend/src/hooks/useSession.ts`
2. Update `useSession.ts` hook to handle paginated response structure with `sessions` array and `next_page_token` properties
3. Update `useThread.ts` hook to handle paginated response structure with `threads` array and `next_page_token` properties
4. Fix function signatures to accept correct number of parameters (0-1 instead of 2)
5. Ensure both hooks properly import CacheContext without errors

## CodeRabbit Issues (if any)
- None - CodeRabbit was rate limited and did not complete review