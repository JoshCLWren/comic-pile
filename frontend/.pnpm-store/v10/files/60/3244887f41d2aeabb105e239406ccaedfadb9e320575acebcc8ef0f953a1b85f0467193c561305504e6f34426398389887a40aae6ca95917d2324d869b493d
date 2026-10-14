import { i as forwardHttpEvents, t as NodeHttpRequestSource } from "../../source-XQ6IsB3Z.js";
import { t as Interceptor } from "../../interceptor-Dn4wuljv.js";
//#region src/interceptors/http/index.ts
/**
* Interceptor for all HTTP requests in Node.js.
*/
var HttpRequestInterceptor = class extends Interceptor {
	static {
		this.symbol = Symbol.for("http-request-interceptor");
	}
	predicate() {
		return true;
	}
	setup() {
		const requestSource = Interceptor.singleton(NodeHttpRequestSource);
		requestSource.apply(this);
		this.subscriptions.push(() => {
			requestSource.dispose(this);
		});
		this.subscriptions.push(forwardHttpEvents({
			source: requestSource,
			emitter: this.emitter,
			predicate: () => {
				return true;
			}
		}));
	}
};
//#endregion
export { HttpRequestInterceptor };

//# sourceMappingURL=index.js.map