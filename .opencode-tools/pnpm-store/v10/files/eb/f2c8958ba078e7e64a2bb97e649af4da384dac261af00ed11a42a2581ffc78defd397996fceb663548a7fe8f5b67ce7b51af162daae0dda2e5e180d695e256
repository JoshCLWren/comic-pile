//#region src/index.d.ts
interface MatchResult {
  matches: boolean;
  params: MatchPatternParams;
}
type MatchPatternInput = string | URL;
type MatchPatternParams = Record<string, string | Array<string>>;
/**
 * Match a URL against the given pattern.
 * @example
 * matchPattern('http://localhost/user/:userId', 'http://localhost/user/123')
 * // { matches: true, params: { userId: '123' } }
 */
declare function matchPattern(pattern: string, input: MatchPatternInput): MatchResult;
//#endregion
export { MatchPatternInput, MatchPatternParams, MatchResult, matchPattern };