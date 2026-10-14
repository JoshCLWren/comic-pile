import { a as RequestHandler, c as RequestHandlerOptions, g as ResponseResolutionContext, h as StrictRequest, l as ResponseResolver, n as DefaultBodyType, o as RequestHandlerDefaultInfo, s as RequestHandlerExecutionResult, u as ResponseResolverFinalizeFunction, y as MaybePromise } from "../_chunks/request-handler.js";
import { c as WebSocketHandler, f as WebSocketResolutionContext, l as WebSocketHandlerConnection, p as kConnect } from "../_chunks/handlers-controller.js";
import { n as Path, r as PathParams, t as Match } from "../_chunks/match-request-url.js";
import { Emitter, TypedEvent } from "rettime";
import { WebSocketClientHandle, WebSocketConnectionEventData, WebSocketServerHandle } from "@mswjs/interceptors/WebSocket";
import { DocumentNode, GraphQLError, OperationTypeNode } from "graphql";
//#region src/graphql/parse-graphql-request.d.ts
interface ParsedGraphQLQuery {
  /**
   * Undefined if the document has no operation matching the
   * requested operation name.
   */
  operationType?: OperationTypeNode;
  operationName?: string;
}
type ParsedGraphQLRequest<VariablesType extends GraphQLVariables = GraphQLVariables> = (ParsedGraphQLQuery & {
  query: string;
  variables?: VariablesType;
}) | undefined;
type GraphQLMultipartRequestBody = {
  operations: string;
  map?: string;
} & {
  [fileName: string]: File;
};
//#endregion
//#region src/graphql/graphql-handler.d.ts
interface DocumentTypeDecoration<Result = {
  [key: string]: any;
}, Variables = {
  [key: string]: any;
}> {
  __apiType?: (variables: Variables) => Result;
  __resultType?: Result;
  __variablesType?: Variables;
}
type GraphQLOperationType = OperationTypeNode | 'all';
type GraphQLHandlerNameSelector = DocumentNode | RegExp | string;
type GraphQLQuery = Record<string, any> | null;
type GraphQLVariables = Record<string, any>;
interface GraphQLHandlerInfo extends RequestHandlerDefaultInfo {
  operationType: GraphQLOperationType;
  operationName: GraphQLHandlerNameSelector | GraphQLCustomPredicate;
}
type GraphQLRequestParsedResult = {
  match: Match;
  cookies: Record<string, string>;
} & (ParsedGraphQLRequest<GraphQLVariables> |
/**
 * An empty version of the ParsedGraphQLRequest
 * which simplifies the return type of the resolver
 * when the request is to a non-matching endpoint
 */
{
  operationType?: undefined;
  operationName?: undefined;
  query?: undefined;
  variables?: undefined;
});
type GraphQLResolverExtras<Variables extends GraphQLVariables> = {
  query: string;
  operationName: string;
  variables: Variables;
  cookies: Record<string, string>;
};
type GraphQLRequestBody<VariablesType extends GraphQLVariables> = GraphQLJsonRequestBody<VariablesType> | GraphQLMultipartRequestBody | Record<string, any> | undefined;
interface GraphQLJsonRequestBody<Variables extends GraphQLVariables> {
  query: string;
  variables?: Variables;
}
type GraphQLResponseBody<BodyType extends DefaultBodyType> = {
  data?: BodyType | null;
  errors?: readonly Partial<GraphQLError>[] | null;
  extensions?: Record<string, any>;
} | null | undefined;
type GraphQLCustomPredicate = (args: {
  request: Request;
  query: string;
  operationType: GraphQLOperationType;
  operationName: string;
  variables: GraphQLVariables;
  cookies: Record<string, string>;
}) => GraphQLCustomPredicateResult | Promise<GraphQLCustomPredicateResult>;
type GraphQLCustomPredicateResult = boolean | {
  matches: boolean;
};
type GraphQLPredicate<Query = any, Variables = any> = GraphQLHandlerNameSelector | DocumentTypeDecoration<Query, Variables> | GraphQLCustomPredicate;
export declare class GraphQLHandler extends RequestHandler<GraphQLHandlerInfo, GraphQLRequestParsedResult, GraphQLResolverExtras<any>> {
  #private;
  private endpoint;
  static parsedRequestCache: WeakMap<Request, ParsedGraphQLRequest<GraphQLVariables>>;
  /**
   * Creates a GraphQL handler information object from the given
   * operation predicate. Normalizes `DocumentNode` and typed document
   * string predicates to plain operation names.
   */
  static parseGraphQLRequestInfo(args: {
    operationType: GraphQLOperationType;
    predicate: GraphQLPredicate;
    url: Path;
  }): GraphQLHandlerInfo;
  constructor(operationType: GraphQLOperationType, predicate: GraphQLPredicate, endpoint: Path, resolver: ResponseResolver<GraphQLResolverExtras<any>, any, any>, options?: RequestHandlerOptions);
  /**
   * Parses the request body, once per request, cached across all
   * GraphQL handlers. This is done to avoid multiple parsing of the
   * request body, which each requires a clone of the request.
   */
  parseGraphQLRequestOrGetFromCache(request: Request): Promise<ParsedGraphQLRequest<GraphQLVariables>>;
  parse(args: {
    request: Request;
  }): Promise<GraphQLRequestParsedResult>;
  predicate(args: {
    request: Request;
    parsedResult: GraphQLRequestParsedResult;
  }): Promise<boolean>;
  run(args: {
    request: StrictRequest<any>;
    requestId: string;
    resolutionContext?: ResponseResolutionContext;
  }): Promise<RequestHandlerExecutionResult<GraphQLRequestParsedResult> | null>;
  private matchOperationName;
  protected extendResolverArgs(args: {
    request: Request;
    parsedResult: GraphQLRequestParsedResult;
  }): {
    query: string;
    operationType: OperationTypeNode;
    operationName: string;
    variables: GraphQLVariables;
    cookies: Record<string, string>;
  };
  log(args: {
    request: Request;
    response: Response;
    parsedResult: GraphQLRequestParsedResult;
  }): Promise<void>;
}
//#endregion
//#region src/graphql/graphql-subscription.d.ts
interface GraphQLWebSocketSubscribePayload<Variables extends GraphQLVariables = GraphQLVariables> {
  operationName?: string | null;
  query: string;
  variables?: Variables;
  extensions?: Record<string, unknown>;
}
interface GraphQLWebSocketSubscribeMessage<Variables extends GraphQLVariables = GraphQLVariables> {
  type: 'subscribe';
  id: string;
  payload: GraphQLWebSocketSubscribePayload<Variables>;
}
interface GraphQLWebSocketCompleteMessage {
  type: 'complete';
  id: string;
}
interface GraphQLWebSocketNextMessage {
  type: 'next';
  id: string;
  payload: GraphQLSubscriptionPayload;
}
interface GraphQLWebSocketErrorMessage {
  type: 'error';
  id: string;
  payload: ReadonlyArray<Partial<GraphQLError>>;
}
/**
 * A GraphQL execution result published to a subscription.
 */
interface GraphQLSubscriptionPayload<Query extends GraphQLQuery = GraphQLQuery> {
  data?: Query | null;
  errors?: ReadonlyArray<Partial<GraphQLError>> | null;
  extensions?: Record<string, unknown>;
}
/**
 * A subscriber provided by a `GraphQLSubscriptionHandler` for a particular
 * WebSocket connection. Returns true if the handler matched the parsed
 * subscribe operation and resolved it.
 */
type GraphQLSubscriptionSubscriber = (args: {
  node: ParsedGraphQLQuery;
  message: GraphQLWebSocketSubscribeMessage;
}) => boolean;
interface GraphQLSubscriptionSubscriberEntry {
  transport: GraphQLSubscriptionTransportHandler;
  subscriber: GraphQLSubscriptionSubscriber;
}
type GraphQLSubscriptionCleanup = () => MaybePromise<void>;
interface GraphQLSubscriptionConnection {
  client: WebSocketClientHandle;
  server: WebSocketServerHandle;
  subscribers: Map<WebSocketHandler, GraphQLSubscriptionSubscriberEntry>;
  /**
   * The active subscriptions of this connection, mapped to the cleanups
   * scheduled for them via the resolver's `finalize()`.
   */
  subscriptions: Map<string, Array<GraphQLSubscriptionCleanup>>;
  events?: WebSocketResolutionContext['events'];
  /**
   * The payload of the client's `connection_init` message (i.e. the
   * `connectionParams` of the GraphQL client). Kept so it can be
   * replayed to the original server on passthrough.
   */
  connectionParams?: Record<string, unknown>;
  /**
   * Resolves once the original server has acknowledged this connection.
   * The upstream session is established once per connection, no matter
   * how many subscriptions pass through it.
   */
  upstreamSession?: Promise<void>;
}
/**
 * A WebSocket handler that only matches connections that requested the
 * `graphql-transport-ws` protocol. Connections without it (e.g.
 * arbitrary non-GraphQL WebSockets whose URL matched a permissive
 * endpoint like a wildcard link) are left unhandled so they follow the
 * regular unhandled connection flow (warnings, passthrough).
 */
declare abstract class GraphQLWebSocketHandler extends WebSocketHandler {
  run(connection: WebSocketConnectionEventData, resolutionContext?: WebSocketResolutionContext): Promise<WebSocketHandlerConnection | null>;
}
/**
 * A WebSocket handler implementing the `graphql-transport-ws` protocol
 * session for a single GraphQL endpoint. One transport is shared across
 * all subscription handlers created from the same `graphql.link()` call
 * (attached to each of them as a sibling handler).
 *
 * The transport owns the protocol/session concerns: connection
 * acknowledgement, keep-alive, the per-connection registry of active
 * subscriptions, and dispatching parsed `subscribe` operations to the
 * matching subscription handler.
 */
declare class GraphQLSubscriptionTransportHandler extends GraphQLWebSocketHandler {
  #private;
  /**
   * Register the given handler as a subscriber to the GraphQL
   * subscriptions on the given WebSocket connection. Subscribers are
   * dispatched in registration order, which follows the handlers
   * resolution order (runtime handlers take precedence).
   */
  subscribe(connection: WebSocketHandlerConnection, handler: WebSocketHandler, subscriber: GraphQLSubscriptionSubscriber): void;
  getConnection(clientId: string): GraphQLSubscriptionConnection | undefined;
  run(connection: WebSocketConnectionEventData, resolutionContext?: WebSocketResolutionContext): Promise<WebSocketHandlerConnection | null>;
  /**
   * End the given subscription without notifying the client. Used when
   * the subscription has already been terminated over the wire (e.g. the
   * original server completed it and that frame reached the client).
   */
  endSubscription(args: {
    clientId: string;
    subscriptionId: string;
  }): void;
  /**
   * Schedule a cleanup to run once the given subscription ends.
   *
   * @note If the subscription has already ended by the time this is
   * called, the cleanup runs immediately. The resolver can no longer
   * affect that subscription, so there is nothing left to wait for.
   */
  finalize(args: {
    clientId: string;
    subscriptionId: string;
    cleanup: GraphQLSubscriptionCleanup;
  }): void;
  /**
   * Send a `next` message with the given payload to the subscription.
   */
  publish(args: {
    clientId: string;
    subscriptionId: string;
    payload: GraphQLSubscriptionPayload;
  }): void;
  /**
   * Send a terminal `error` message to the subscription and
   * removes it from the registry of active subscriptions.
   */
  error(args: {
    clientId: string;
    subscriptionId: string;
    errors: ReadonlyArray<Partial<GraphQLError>>;
  }): void;
  /**
   * Send a `complete` message to the subscription and removes it
   * from the registry of active subscriptions.
   */
  complete(args: {
    clientId: string;
    subscriptionId: string;
  }): void;
  /**
   * Drop this transport's subscribers and active subscriptions from the
   * sessions it participates in. The sessions themselves are left intact:
   * they are shared with the other transports of the same connection and
   * own the protocol listeners for as long as the client stays connected.
   *
   * @note This method is invoked automatically when the handlers
   * controller resets the handlers (e.g. `server.resetHandlers()`).
   */
  reset(): void;
  /**
   * Forget the sessions of this transport, ending their subscriptions.
   * @note This method is invoked automatically when the network is
   * disabled (e.g. `server.close()`).
   */
  dispose(): MaybePromise<void>;
  /**
   * @note The transport is the sole owner of logging for GraphQL
   * subscription connections. It logs parsed `graphql-transport-ws`
   * frames instead of raw WebSocket messages.
   */
  log(connection: WebSocketConnectionEventData): () => void;
  protected [kConnect](connection: WebSocketHandlerConnection): boolean;
}
type GraphQLSubscriptionName<Query extends GraphQLQuery = GraphQLQuery, Variables extends GraphQLVariables = GraphQLVariables> = GraphQLHandlerNameSelector | DocumentTypeDecoration<Query, Variables>;
interface GraphQLSubscriptionResolverInfo<Query extends GraphQLQuery = GraphQLQuery, Variables extends GraphQLVariables = GraphQLVariables> {
  /**
   * Path parameters parsed from the WebSocket connection URL.
   */
  params: PathParams;
  /**
   * The name of the intercepted operation.
   */
  operationName: string;
  /**
   * Intercepted GraphQL subscription.
   */
  subscription: GraphQLSubscription<Query, Variables>;
  /**
   * The request that established the WebSocket connection this
   * subscription is multiplexed over.
   */
  request: Request;
  /**
   * Schedule a cleanup to run once this subscription ends and the
   * resolver can no longer affect it: it has been completed (by the mock,
   * the client, or the original server), terminated with errors, or the
   * client has disconnected.
   *
   * @example
   * api.subscription('OnCommentAdded', ({ subscription, finalize }) => {
   *   const interval = setInterval(() => subscription.publish(payload), 1000)
   *   finalize(() => clearInterval(interval))
   * })
   */
  finalize: ResponseResolverFinalizeFunction;
}
type GraphQLSubscriptionResolver<Query extends GraphQLQuery = GraphQLQuery, Variables extends GraphQLVariables = GraphQLVariables> = (info: GraphQLSubscriptionResolverInfo<Query, Variables>) => void;
interface GraphQLSubscriptionHandlerOptions {
  /**
   * Mark this handler as used after its first match.
   * Used handlers do not match subsequent subscriptions.
   */
  once?: boolean;
}
/**
 * A WebSocket handler intercepting GraphQL subscriptions by their
 * operation name. Matching and resolution are delegated to it by the
 * subscription transport (its sibling handler) so the first matching
 * handler wins, respecting runtime handler overrides.
 */
export declare class GraphQLSubscriptionHandler<Query extends GraphQLQuery = GraphQLQuery, Variables extends GraphQLVariables = GraphQLVariables> extends GraphQLWebSocketHandler {
  #private;
  info: GraphQLHandlerInfo;
  isUsed: boolean;
  constructor(args: {
    url: Path;
    operationName: GraphQLSubscriptionName<Query, Variables>;
    transport: GraphQLSubscriptionTransportHandler;
    resolver: GraphQLSubscriptionResolver<Query, Variables>;
    options?: GraphQLSubscriptionHandlerOptions;
  });
  reset(): void;
  /**
   * @note Individual subscription handlers stay silent. The subscription
   * transport owns the GraphQL-aware logging for the entire connection
   * (a logger is attached once per matching handler otherwise).
   */
  log(): () => void;
  protected [kConnect](connection: WebSocketHandlerConnection): boolean;
}
/**
 * Representation of the intercepted GraphQL subscription.
 */
export declare class GraphQLSubscription<Query extends GraphQLQuery = GraphQLQuery, Variables extends GraphQLVariables = GraphQLVariables> {
  #private;
  id: string;
  query: string;
  variables: Variables;
  extensions?: Record<string, unknown>;
  constructor(args: {
    message: GraphQLWebSocketSubscribeMessage;
    clientId: string;
    transport: GraphQLSubscriptionTransportHandler;
  });
  /**
   * Publish an execution result to the subscribed client.
   *
   * @example
   * subscription.publish({
   *   data: {
   *     postAdded: {
   *       id: 'abc-123'
   *     }
   *   }
   * })
   */
  publish(payload: GraphQLSubscriptionPayload<Query>): void;
  /**
   * Use the given `Iterable` or `AsyncIterable` as the source
   * of data for this subscription. Whenever the iterable yields a
   * value, it gets published to this subscription.
   *
   * @example
   * subscription.from(async function* () {
   *   yield { text: 'hello world' }
   * })
   */
  from(source: Iterable<Query> | AsyncIterable<Query>): Promise<void>;
  /**
   * Terminate this subscription with the given errors.
   *
   * @example
   * subscription.error([{ message: 'Something went wrong' }])
   */
  error(errors: ReadonlyArray<Partial<GraphQLError>>): void;
  /**
   * Marks this subscription as complete.
   *
   * @example
   * subscription.complete()
   */
  complete(): void;
  /**
   * Perform this GraphQL subscription as-is.
   * This establishes a connection to the actual server, replays
   * the intercepted subscription, and forwards the server payloads
   * to the GraphQL client. You can intercept, modify, or prevent
   * any of the original server messages.
   *
   * @example
   * const postAddedSubscription = subscription.passthrough()
   * postAddedSubscription.addEventListener('next', (event) => {
   *   event.preventDefault()
   *   event.data.payload.data.postAdded.id = 'mock-id'
   *   subscription.publish(event.data.payload)
   * })
   */
  passthrough(): GraphQLPassthroughSubscription;
}
type GraphQLPassthroughSubscriptionEventMap = {
  connection_ack: TypedEvent;
  next: TypedEvent<GraphQLWebSocketNextMessage>;
  error: TypedEvent<GraphQLWebSocketErrorMessage>;
  complete: TypedEvent<GraphQLWebSocketCompleteMessage>;
};
/**
 * Representation of a GraphQL subscription to the actual server.
 * You interface with this object from the client's perspective.
 */
export declare class GraphQLPassthroughSubscription {
  #private;
  constructor(args: {
    server: WebSocketServerHandle;
    message: GraphQLWebSocketSubscribeMessage;
    upstreamSession: Promise<void>;
    onTerminate: () => void;
  });
  /**
   * Add an event listener to the given GraphQL subscription event.
   *
   * @example
   * const onPostAddedSubscription = subscription.passthrough()
   * onPostAddedSubscription.addEventListener('next', (event) => {
   *   console.log(event.data)
   *   // { id, payload, ... }
   * })
   */
  addEventListener<EventType extends keyof GraphQLPassthroughSubscriptionEventMap & string>(event: EventType, listener: Emitter.Listener<Emitter<GraphQLPassthroughSubscriptionEventMap>, EventType>): void;
  /**
   * Unsubscribe from this passthrough GraphQL subscription.
   * This stops this subscription on the original server.
   *
   * @note Unsubscribing from the original subscription has no
   * effect on the intercepted `subscription` object.
   *
   * @example
   * const onPostAddedSubscription = subscription.passthrough()
   * onPostAddedSubscription.unsubscribe()
   */
  unsubscribe(): void;
}
type GraphQLSubscriptionHandlerFactory = <Query extends GraphQLQuery = GraphQLQuery, Variables extends GraphQLVariables = GraphQLVariables>(operationName: GraphQLSubscriptionName<Query, Variables>, resolver: GraphQLSubscriptionResolver<Query, Variables>, options?: GraphQLSubscriptionHandlerOptions) => GraphQLSubscriptionHandler<Query, Variables>;
/**
 * Create a `subscription()` handler factory bound to the given GraphQL
 * endpoint. All subscription handlers created by the factory share a single
 * subscription transport and a single WebSocket upgrade handler, both
 * attached to each handler as siblings.
 *
 * @example
 * const subscription = createGraphQLSubscriptionHandler('https://api.example.com/graphql')
 * subscription('OnPostAdded', ({ subscription }) => {
 *   subscription.publish({ data: { postAdded: { id: 'abc-123' } } })
 * })
 */
export declare function createGraphQLSubscriptionHandler(url: Path): GraphQLSubscriptionHandlerFactory;
//#endregion
//#region src/graphql/graphql.d.ts
type GraphQLRequestHandler = <Query extends GraphQLQuery = GraphQLQuery, Variables extends GraphQLVariables = GraphQLVariables>(predicate: GraphQLPredicate<Query, Variables>, resolver: GraphQLResponseResolver<[Query] extends [never] ? GraphQLQuery : Query, Variables>, options?: RequestHandlerOptions) => GraphQLHandler;
type GraphQLOperationHandler = <Query extends GraphQLQuery = GraphQLQuery, Variables extends GraphQLVariables = GraphQLVariables>(resolver: GraphQLResponseResolver<[Query] extends [never] ? GraphQLQuery : Query, Variables>, options?: RequestHandlerOptions) => GraphQLHandler;
type GraphQLResponseResolver<Query extends GraphQLQuery = GraphQLQuery, Variables extends GraphQLVariables = GraphQLVariables> = ResponseResolver<GraphQLResolverExtras<Variables>, null, GraphQLResponseBody<[Query] extends [never] ? GraphQLQuery : Query>>;
interface GraphQLLink {
  query: GraphQLRequestHandler;
  mutation: GraphQLRequestHandler;
  operation: GraphQLOperationHandler;
  /**
   * Intercept a GraphQL subscription.
   *
   * @example
   * const api = graphql.link('https://api.example.com/graphql')
   * api.subscription('OnPostAdded', ({ subscription }) => {
   *   subscription.publish({
   *    data: { postAdded: { id: 'abc-123' } },
   *   })
   * })
   */
  subscription: GraphQLSubscriptionHandlerFactory;
}
/**
 * A namespace to intercept and mock GraphQL operations
 *
 * @example
 * const api = graphql.link('https://api.example.com/graphql')
 * api.query('GetUser', resolver)
 * api.mutation('DeletePost', resolver)
 *
 * @see {@link https://mswjs.io/docs/api/graphql `graphql` API reference}
 */
export declare const graphql: {
  /**
   * Intercepts GraphQL operations scoped by the given URL.
   *
   * @example
   * const github = graphql.link('https://api.github.com/graphql')
   * github.query('GetRepo', resolver)
   *
   * @see {@link https://mswjs.io/docs/api/graphql#graphqllinkurl `graphql.link()` API reference}
   */
  link(url: Path): GraphQLLink;
};
//#endregion
export type { GraphQLCustomPredicate, GraphQLJsonRequestBody, GraphQLLink, GraphQLOperationHandler, GraphQLOperationType, GraphQLPassthroughSubscriptionEventMap, GraphQLQuery, GraphQLRequestBody, GraphQLRequestHandler, GraphQLResponseBody, GraphQLResponseResolver, GraphQLSubscriptionHandlerFactory, GraphQLSubscriptionHandlerOptions, GraphQLSubscriptionName, GraphQLSubscriptionPayload, GraphQLSubscriptionResolver, GraphQLSubscriptionResolverInfo, GraphQLVariables, ParsedGraphQLRequest };
//# sourceMappingURL=index.d.ts.map