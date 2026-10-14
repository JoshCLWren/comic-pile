import { c as RequestHandlerOptions, l as ResponseResolver, n as DefaultBodyType } from "./request-handler.js";
import { r as PathParams } from "./match-request-url.js";
import { c as HttpRequestResolverExtras, n as HttpHandler, s as HttpRequestPredicate } from "./http-handler.js";
//#region src/http/http.d.ts
type HttpRequestHandler = <Params extends PathParams<keyof Params> = PathParams, RequestBodyType extends DefaultBodyType = DefaultBodyType, ResponseBodyType extends DefaultBodyType = undefined>(predicate: HttpRequestPredicate<Params>, resolver: HttpResponseResolver<Params, RequestBodyType, ResponseBodyType>, options?: RequestHandlerOptions) => HttpHandler;
type HttpResponseResolver<Params extends PathParams<keyof Params> = PathParams, RequestBodyType extends DefaultBodyType = DefaultBodyType, ResponseBodyType extends DefaultBodyType = DefaultBodyType> = ResponseResolver<HttpRequestResolverExtras<Params>, RequestBodyType, ResponseBodyType>;
/**
 * A namespace to intercept and mock HTTP requests.
 *
 * @example
 * http.get('/user', resolver)
 * http.post('/post/:id', resolver)
 *
 * @see {@link https://mswjs.io/docs/api/http `http` API reference}
 */
declare const http: {
  all: HttpRequestHandler;
  head: HttpRequestHandler;
  get: HttpRequestHandler;
  post: HttpRequestHandler;
  put: HttpRequestHandler;
  delete: HttpRequestHandler;
  patch: HttpRequestHandler;
  options: HttpRequestHandler;
};
//#endregion
export { HttpResponseResolver as n, http as r, HttpRequestHandler as t };
//# sourceMappingURL=http.d.ts.map