//#region src/utils/buffer-utils.ts
const encoder = new TextEncoder();
function encodeBuffer(text) {
	return encoder.encode(text);
}
function decodeBuffer(buffer, encoding) {
	return new TextDecoder(encoding).decode(buffer);
}
function toBuffer(data, encoding) {
	if (Buffer.isBuffer(data)) return data;
	if (data instanceof Uint8Array) return Buffer.from(data.buffer);
	return Buffer.from(data, encoding);
}
//#endregion
//#region src/utils/get-value-by-symbol.ts
/**
* Returns the value behind the symbol with the given name.
*/
function getValueBySymbol(symbolName, source) {
	const symbol = Object.getOwnPropertySymbols(source).find((symbol) => {
		return symbol.description === symbolName;
	});
	if (symbol) return Reflect.get(source, symbol);
}
//#endregion
export { toBuffer as i, decodeBuffer as n, encodeBuffer as r, getValueBySymbol as t };

//# sourceMappingURL=get-value-by-symbol-Cx7kBFyN.js.map