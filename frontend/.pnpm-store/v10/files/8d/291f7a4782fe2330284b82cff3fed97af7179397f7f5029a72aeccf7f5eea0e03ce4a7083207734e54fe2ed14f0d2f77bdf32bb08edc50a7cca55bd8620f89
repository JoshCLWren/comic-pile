//#region src/core/utils/matching/match-request-url.d.ts
type Path = string | RegExp;
type PathParams<KeyType extends keyof any = string> = { [ParamName in KeyType]?: string | ReadonlyArray<string>; };
interface Match {
  matches: boolean;
  params?: PathParams;
}
/**
 * Match the given URL against a path pattern.
 */
declare function matchRequestUrl(url: URL, pattern: Path, baseUrl?: string): Match;
//#endregion
export { matchRequestUrl as i, Path as n, PathParams as r, Match as t };
//# sourceMappingURL=match-request-url.d.ts.map