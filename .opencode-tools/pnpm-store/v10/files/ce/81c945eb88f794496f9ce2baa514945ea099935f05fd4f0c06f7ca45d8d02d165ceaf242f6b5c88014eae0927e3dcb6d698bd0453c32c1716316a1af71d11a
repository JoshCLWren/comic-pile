import { Writable } from 'node:stream';
import { Parser, type ParserOptions, type TreeAdapterTypeMap, type DefaultTreeAdapterMap } from 'parse5';
/**
 * Streaming HTML parser with scripting support.
 * A [writable stream](https://nodejs.org/api/stream.html#stream_class_stream_writable).
 *
 * @example
 *
 * ```js
 * const ParserStream = require('parse5-parser-stream');
 * const http = require('http');
 * const { finished } = require('node:stream');
 *
 * // Fetch the page content and obtain it's <head> node
 * http.get('http://inikulin.github.io/parse5/', res => {
 *     const parser = new ParserStream();
 *
 *     finished(parser, () => {
 *         console.log(parser.document.childNodes[1].childNodes[0].tagName); //> 'head'
 *     });
 *
 *     res.pipe(parser);
 * });
 * ```
 *
 */
export declare class ParserStream<T extends TreeAdapterTypeMap = DefaultTreeAdapterMap> extends Writable {
    parser: Parser<T>;
    static getFragmentStream<T extends TreeAdapterTypeMap>(fragmentContext?: T['parentNode'] | null, options?: ParserOptions<T>): ParserStream<T>;
    private lastChunkWritten;
    private writeCallback;
    private pendingHtmlInsertions;
    /** The resulting document node. */
    get document(): T['document'];
    getFragment(): T['documentFragment'];
    /**
     * Synchronously delivers buffered character tokens to the tree builder without ending the input stream.
     * Incomplete tags and character references are retained for subsequent writes. This does not resume a
     * suspended script or process queued writes, and must not be called from a parser callback.
     *
     * Flushing splits character-token runs. Their source locations do not extend through subsequently
     * ignored input, such as CDATA delimiters or the leading newline in a `pre` element, so text-node
     * source ranges can differ from parsing without flushing.
     *
     * @example
     *
     * ```js
     * const stream = new ParserStream();
     * stream.write('<p>hello');
     * stream.flushCharacters();
     * // The paragraph's text is now available in `stream.document`.
     * stream.end(' world</p>');
     * ```
     */
    flushCharacters(): void;
    /**
     * @param options Parsing options.
     */
    constructor(options?: ParserOptions<T>, parser?: Parser<T>);
    _write(chunk: string, _encoding: string, callback: () => void): void;
    end(chunk?: any, encoding?: any, callback?: any): any;
}
export interface ParserStream<T extends TreeAdapterTypeMap = DefaultTreeAdapterMap> {
    /**
     * Raised when parser encounters a `<script>` element. If this event has listeners, parsing will be suspended once
     * it is emitted. So, if `<script>` has the `src` attribute, you can fetch it, execute and then resume parsing just
     * like browsers do.
     *
     * @example
     *
     * ```js
     * const ParserStream = require('parse5-parser-stream');
     * const http = require('http');
     *
     * const parser = new ParserStream();
     *
     * parser.on('script', (scriptElement, documentWrite, resume) => {
     *     const src = scriptElement.attrs.find(({ name }) => name === 'src').value;
     *
     *     http.get(src, res => {
     *         // Fetch the script content, execute it with DOM built around `parser.document` and
     *         // `document.write` implemented using `documentWrite`.
     *         ...
     *         // Then resume parsing.
     *         resume();
     *     });
     * });
     *
     * parser.end('<script src="example.com/script.js"></script>');
     * ```
     *
     * @param event Name of the event
     * @param handler
     */
    on(event: 'script', handler: (scriptElement: T['element'], documentWrite: (html: string) => void, resume: () => void) => void): void;
    /**
     * Base event handler.
     *
     * @param event Name of the event
     * @param handler Event handler
     */
    on(event: string, handler: (...args: any[]) => void): this;
}
