import { FetchResponse } from "@mswjs/interceptors";
//#region src/core/type-utils.d.ts
type MaybePromise<T> = T | Promise<T>;
/**
 * Blocks inference from the annotated position, like the built-in `NoInfer`,
 * but resolves to a plain type once instantiated. The built-in `NoInfer` stays
 * an opaque wrapper, which makes TypeScript report response body mismatches on
 * the whole object literal instead of the offending property.
 */
type TransparentNoInfer<T> = [T][T extends any ? 0 : never];
/**
 * Turns a union of types into an intersection of its members.
 */
type UnionToIntersection<Union> = (Union extends unknown ? (member: Union) => void : never) extends ((member: infer Intersection) => void) ? Intersection : never;
//#endregion
//#region src/core/handlers/handler.d.ts
type HandlerKind = 'request' | 'websocket';
/**
 * The base class for all the handlers.
 */
declare abstract class Handler {
  /**
   * The kind of the network frame this handler handles.
   */
  abstract readonly kind: HandlerKind;
  /**
   * Reset the runtime state this handler accumulated while handling
   * the network (e.g. generator resolver progress).
   *
   * @note This method is invoked automatically when the handlers are
   * reset (e.g. `server.resetHandlers()`).
   */
  reset(): void;
  /**
   * Restore this handler so it can handle the network again after
   * being exhausted (e.g. via `{ once: true }`).
   *
   * @note This method is invoked automatically when the handlers are
   * restored (e.g. `server.restoreHandlers()`).
   */
  restore(): void;
  /**
   * Release the resources held by this handler.
   *
   * @note This method is invoked automatically when the network is
   * disabled (e.g. `server.close()`). Override it in the handlers that
   * hold onto anything beyond a single frame, like timers, connections,
   * or event listeners. Returning a promise makes the network await
   * this handler's disposal before it tears itself down.
   */
  dispose(): MaybePromise<void>;
}
//#endregion
//#region src/core/utils/execute-handlers.d.ts
interface ResponseResolutionContext {
  /**
   * A base url to use when resolving relative urls.
   * @note This is primarily used by the `@mswjs/http-middleware`
   * to resolve relative urls in the context of the running server
   */
  baseUrl?: string;
  quiet?: boolean;
}
//#endregion
//#region src/http/symbols.d.ts
/**
 * Associates the mocked response body type with the response instance
 * for stricter typing of the response resolvers.
 */
declare const bodyType: unique symbol;
//#endregion
//#region src/http/http-response.d.ts
interface HttpResponseInit extends ResponseInit {
  type?: ResponseType;
}
type DefaultUnsafeFetchResponse = Response & {
  [bodyType]?: never;
};
interface StrictRequest<BodyType extends JsonBodyType> extends Request {
  json(): Promise<BodyType>;
  clone(): StrictRequest<BodyType>;
}
/**
 * A drop-in replacement for the standard `Response` class
 * to allow additional features, like mocking the response `Set-Cookie` header.
 *
 * @example
 * new HttpResponse('Hello world', { status: 201 })
 * HttpResponse.json({ name: 'John' })
 * HttpResponse.formData(form)
 *
 * @see {@link https://mswjs.io/docs/api/http-response `HttpResponse` API reference}
 */
declare class HttpResponse<BodyType extends DefaultBodyType> extends FetchResponse {
  readonly [bodyType]: BodyType;
  constructor(body?: TransparentNoInfer<BodyType> | null, init?: HttpResponseInit);
  static error(): HttpResponse<any>;
  /**
   * Create a `Response` with a `Content-Type: "text/plain"` body.
   * @example
   * HttpResponse.text('hello world')
   * HttpResponse.text('Error', { status: 500 })
   */
  static text<BodyType extends string>(body?: TransparentNoInfer<BodyType> | null, init?: HttpResponseInit): HttpResponse<BodyType>;
  /**
   * Create a `Response` with a `Content-Type: "application/json"` body.
   * @example
   * HttpResponse.json({ firstName: 'John' })
   * HttpResponse.json({ error: 'Not Authorized' }, { status: 401 })
   */
  static json<BodyType extends JsonBodyType>(body?: TransparentNoInfer<BodyType> | null | undefined, init?: HttpResponseInit): HttpResponse<BodyType>;
  /**
   * Create a `Response` with a `Content-Type: "application/xml"` body.
   * @example
   * HttpResponse.xml(`<user name="John" />`)
   * HttpResponse.xml(`<article id="abc-123" />`, { status: 201 })
   */
  static xml<BodyType extends string>(body?: BodyType | null, init?: HttpResponseInit): HttpResponse<BodyType>;
  /**
   * Create a `Response` with a `Content-Type: "text/html"` body.
   * @example
   * HttpResponse.html(`<p class="author">Jane Doe</p>`)
   * HttpResponse.html(`<main id="abc-123">Main text</main>`, { status: 201 })
   */
  static html<BodyType extends string>(body?: BodyType | null, init?: HttpResponseInit): HttpResponse<BodyType>;
  /**
   * Create a `Response` with an `ArrayBuffer` body.
   * @example
   * const buffer = new ArrayBuffer(3)
   * const view = new Uint8Array(buffer)
   * view.set([1, 2, 3])
   *
   * HttpResponse.arrayBuffer(buffer)
   */
  static arrayBuffer<BodyType extends ArrayBuffer | SharedArrayBuffer>(body?: BodyType, init?: HttpResponseInit): HttpResponse<BodyType>;
  /**
   * Create a `Response` with a `FormData` body.
   * @example
   * const data = new FormData()
   * data.set('name', 'Alice')
   *
   * HttpResponse.formData(data)
   */
  static formData(body?: FormData, init?: HttpResponseInit): HttpResponse<FormData>;
}
//#endregion
//#region src/core/handlers/request-handler.d.ts
type DefaultRequestMultipartBody = Record<string, string | File | Array<string | File>>;
type DefaultBodyType = Record<string, any> | DefaultRequestMultipartBody | string | number | boolean | null | undefined;
type JsonBodyType = Record<string, any> | string | number | boolean | null | undefined;
interface RequestHandlerDefaultInfo {
  header: string;
}
interface RequestHandlerInternalInfo {
  callFrame?: string;
}
type ResponseResolverReturnType<ResponseBodyType extends DefaultBodyType = undefined> = ([ResponseBodyType] extends [undefined] ? Response : ResponseBodyType extends Record<string, any> | undefined ? HttpResponse<ResponseBodyType> | DefaultUnsafeFetchResponse : HttpResponse<ResponseBodyType>) | undefined | void;
type MaybeAsyncResponseResolverReturnType<ResponseBodyType extends DefaultBodyType> = MaybePromise<ResponseResolverReturnType<ResponseBodyType>>;
type AsyncResponseResolverReturnType<ResponseBodyType extends DefaultBodyType> = MaybePromise<ResponseResolverReturnType<ResponseBodyType> | Iterable<MaybeAsyncResponseResolverReturnType<ResponseBodyType>, MaybeAsyncResponseResolverReturnType<ResponseBodyType>, MaybeAsyncResponseResolverReturnType<ResponseBodyType>> | AsyncIterable<MaybeAsyncResponseResolverReturnType<ResponseBodyType>, MaybeAsyncResponseResolverReturnType<ResponseBodyType>, MaybeAsyncResponseResolverReturnType<ResponseBodyType>>>;
type ResponseResolverInfo<ResolverExtraInfo extends Record<string, unknown>, RequestBodyType extends DefaultBodyType = DefaultBodyType> = {
  request: StrictRequest<RequestBodyType>;
  requestId: string;
  /**
   * Schedule a callback to run after this response resolver completes.
   * Handy for cleaning up the side effects introduced in the resolver.
   *
   * For responses with a `ReadableStream` body (including `sse()` handlers),
   * the callback runs once the response stream settles: it is read to
   * completion, errored, or canceled, or the request is aborted.
   * @example
   * sse('/', ({ client, finalize }) => {
   *   const interval = setInterval(() => client.send({ data: 'ping' }))
   *   finalize(() => clearInterval(interval))
   * })
   */
  finalize: ResponseResolverFinalizeFunction;
} & ResolverExtraInfo;
type ResponseResolverFinalizeFunction = (callback: () => MaybePromise<void>) => void;
type ResponseResolver<ResolverExtraInfo extends Record<string, unknown> = Record<string, unknown>, RequestBodyType extends DefaultBodyType = DefaultBodyType, ResponseBodyType extends DefaultBodyType = undefined> = (info: ResponseResolverInfo<ResolverExtraInfo, RequestBodyType>) => AsyncResponseResolverReturnType<ResponseBodyType>;
interface RequestHandlerArgs<HandlerInfo, HandlerOptions extends RequestHandlerOptions> {
  info: HandlerInfo;
  resolver: ResponseResolver<any>;
  options?: HandlerOptions;
}
interface RequestHandlerOptions {
  once?: boolean;
}
interface RequestHandlerExecutionResult<ParsedResult extends object | undefined> {
  handler: RequestHandler;
  parsedResult?: ParsedResult;
  request: Request;
  requestId: string;
  response?: Response;
}
declare abstract class RequestHandler<HandlerInfo extends RequestHandlerDefaultInfo = RequestHandlerDefaultInfo, ParsedResult extends Record<string, any> | undefined = any, ResolverExtras extends Record<string, unknown> = any, HandlerOptions extends RequestHandlerOptions = RequestHandlerOptions> extends Handler {
  static cache: WeakMap<StrictRequest<DefaultBodyType>, StrictRequest<DefaultBodyType>>;
  readonly kind = "request";
  protected resolver: ResponseResolver<ResolverExtras, any, any>;
  private resolverIterator?;
  private resolverIteratorResult?;
  private resolverIteratorCleanups?;
  private options?;
  private scheduledCleanups;
  info: HandlerInfo & RequestHandlerInternalInfo;
  /**
   * Indicates whether this request handler has been used
   * (its resolver has successfully executed).
   */
  isUsed: boolean;
  constructor(args: RequestHandlerArgs<HandlerInfo, HandlerOptions>);
  /**
   * Reset the runtime state accumulated during response resolution,
   * such as generator iterator progress. Called when this handler is
   * removed from the active handlers list so re-adding it later starts
   * from a clean state.
   */
  reset(): void;
  /**
   * Restore this handler so it can match requests again after being
   * exhausted (e.g. via `{ once: true }`). Also clears any accumulated
   * resolution state.
   */
  restore(): void;
  /**
   * Determine if the intercepted request should be mocked.
   */
  abstract predicate(args: {
    request: Request;
    parsedResult: ParsedResult;
    resolutionContext?: ResponseResolutionContext;
  }): boolean | Promise<boolean>;
  /**
   * Print out the successfully handled request.
   */
  abstract log(args: {
    request: Request;
    response: Response;
    parsedResult: ParsedResult;
  }): void;
  /**
   * Parse the intercepted request to extract additional information from it.
   * Parsed result is then exposed to other methods of this request handler.
   */
  parse(_args: {
    request: Request;
    resolutionContext?: ResponseResolutionContext;
  }): Promise<ParsedResult>;
  /**
   * Test if this handler matches the given request.
   *
   * This method is not used internally but is exposed
   * as a convenience method for consumers writing custom
   * handlers.
   */
  test(args: {
    request: Request;
    resolutionContext?: ResponseResolutionContext;
  }): Promise<boolean>;
  protected extendResolverArgs(_args: {
    request: Request;
    parsedResult: ParsedResult;
  }): ResolverExtras;
  private cloneRequestOrGetFromCache;
  /**
   * Execute this request handler and produce a mocked response
   * using the given resolver function.
   */
  run(args: {
    request: StrictRequest<any>;
    requestId: string;
    resolutionContext?: ResponseResolutionContext;
  }): Promise<RequestHandlerExecutionResult<ParsedResult> | null>;
  private wrapResolver;
  private createExecutionResult;
  private scheduleCleanup;
  private exhaustCleanups;
  /**
   * Remove and return the cleanups scheduled for the given request
   * (or the pending iterator cleanups for generator resolvers).
   */
  private takeScheduledCleanups;
  private runScheduledCleanups;
  /**
   * Conclude the response resolution for the given request.
   * Runs the scheduled cleanups immediately for responses without a
   * `ReadableStream` body. For streamed responses, returns an observed
   * copy of the response and defers the cleanups until its body settles
   * (is read to completion, errored, or canceled) or the request is
   * aborted, whichever comes first.
   */
  private complete;
}
//#endregion
export { Handler as _, RequestHandler as a, UnionToIntersection as b, RequestHandlerOptions as c, ResponseResolverInfo as d, ResponseResolverReturnType as f, ResponseResolutionContext as g, StrictRequest as h, JsonBodyType as i, ResponseResolver as l, HttpResponseInit as m, DefaultBodyType as n, RequestHandlerDefaultInfo as o, HttpResponse as p, DefaultRequestMultipartBody as r, RequestHandlerExecutionResult as s, AsyncResponseResolverReturnType as t, ResponseResolverFinalizeFunction as u, HandlerKind as v, MaybePromise as y };
//# sourceMappingURL=request-handler.d.ts.map