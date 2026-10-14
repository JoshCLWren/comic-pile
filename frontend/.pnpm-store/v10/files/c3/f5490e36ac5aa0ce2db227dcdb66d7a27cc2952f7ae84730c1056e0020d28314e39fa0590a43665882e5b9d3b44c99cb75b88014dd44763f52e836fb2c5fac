//#region src/index.ts
const ASTERISK = 42;
const SLASH = 47;
const COLON = 58;
const QUESTION_MARK = 63;
const PLUS = 43;
const BACKSLASH = 92;
const UNDERSCORE = 95;
const OPEN_BRACKET = 91;
const CLOSE_BRACKET = 93;
const UPPERCASE_A = 65;
const UPPERCASE_Z = 90;
const MAX_INPUT_LENGTH = 8192;
const PATTERN_CACHE_LIMIT = 1e3;
const MAX_MATCH_STEPS = 1e5;
const PATTERN_CACHE = /* @__PURE__ */ new Map();
const NO_MATCH = Object.freeze({
	matches: false,
	params: Object.freeze(Object.create(null))
});
function isIdentStartCode(code) {
	return code >= 97 && code <= 122 || code >= 65 && code <= 90 || code === UNDERSCORE;
}
function isIdentCharCode(code) {
	return isIdentStartCode(code) || code >= 48 && code <= 57;
}
/**
* Lowercase the case-insensitive parts of a URL — the scheme and
* the host. Applies to both patterns and inputs so that
* `http://EXAMPLE.com` matches `http://example.com`. The userinfo
* (`user:pass@`), the path, and `:param` names within the host are
* case-sensitive and preserved as-is.
*/
function lowercaseSchemeAndHost(url) {
	const schemeSeparatorIndex = url.indexOf("://");
	if (schemeSeparatorIndex === -1) return url;
	if (url.indexOf("/") !== schemeSeparatorIndex + 1) return url;
	const authorityStart = schemeSeparatorIndex + 3;
	let hostEnd = url.indexOf("/", authorityStart);
	if (hostEnd === -1) hostEnd = url.length;
	let needsLowercasing = false;
	for (let i = 0; i < hostEnd; i++) {
		const code = url.charCodeAt(i);
		if (code >= UPPERCASE_A && code <= UPPERCASE_Z || code > 127) {
			needsLowercasing = true;
			break;
		}
	}
	if (!needsLowercasing) return url;
	const userinfoEnd = url.lastIndexOf("@", hostEnd - 1);
	let result = "";
	let plainStart = 0;
	let inBrackets = false;
	let i = 0;
	while (i < hostEnd) {
		if (i === authorityStart && userinfoEnd >= authorityStart) {
			result += url.slice(plainStart, i).toLowerCase();
			result += url.slice(i, userinfoEnd + 1);
			i = userinfoEnd + 1;
			plainStart = i;
			continue;
		}
		const code = url.charCodeAt(i);
		if (code === OPEN_BRACKET) inBrackets = true;
		else if (code === CLOSE_BRACKET) inBrackets = false;
		else if (code === COLON && !inBrackets && i + 1 < hostEnd && isIdentStartCode(url.charCodeAt(i + 1))) {
			result += url.slice(plainStart, i).toLowerCase();
			const paramStart = i;
			i++;
			while (i < hostEnd && isIdentCharCode(url.charCodeAt(i))) i++;
			result += url.slice(paramStart, i);
			plainStart = i;
			continue;
		}
		i++;
	}
	result += url.slice(plainStart, hostEnd).toLowerCase();
	result += url.slice(hostEnd);
	return result;
}
function parsePatternOrGetFromCache(pattern) {
	let parsed = PATTERN_CACHE.get(pattern);
	if (parsed === void 0) {
		const normalizedPattern = lowercaseSchemeAndHost(pattern);
		const tokens = parsePattern(normalizedPattern);
		let isLiteralOnly = normalizedPattern.indexOf("\\") === -1;
		for (let i = 0; isLiteralOnly && i < tokens.length; i++) if (tokens[i].type !== 0) isLiteralOnly = false;
		const lastToken = tokens[tokens.length - 1];
		const hasTrailingSlash = lastToken !== void 0 && lastToken.type === 0 && lastToken.value.length > 0 && lastToken.value.charCodeAt(lastToken.value.length - 1) === SLASH;
		if (PATTERN_CACHE.size >= PATTERN_CACHE_LIMIT) PATTERN_CACHE.delete(PATTERN_CACHE.keys().next().value);
		parsed = {
			tokens,
			isLiteralOnly,
			hasTrailingSlash,
			normalizedPattern
		};
		PATTERN_CACHE.set(pattern, parsed);
	}
	return parsed;
}
function parsePattern(pattern) {
	const tokens = [];
	let i = 0;
	const length = pattern.length;
	let inBrackets = false;
	while (i < length) {
		const code = pattern.charCodeAt(i);
		if (code === BACKSLASH && i + 1 < length) {} else if (code === ASTERISK && !inBrackets) {
			tokens.push({
				type: 1,
				nextLiteral: void 0
			});
			i++;
			continue;
		} else if (code === COLON && !inBrackets && i + 1 < length && isIdentStartCode(pattern.charCodeAt(i + 1))) {
			const start = ++i;
			while (i < length && isIdentCharCode(pattern.charCodeAt(i))) i++;
			const name = pattern.slice(start, i);
			let modifier = "";
			if (i < length) {
				const mod = pattern.charCodeAt(i);
				if (mod === QUESTION_MARK || mod === PLUS || mod === ASTERISK) {
					modifier = pattern[i];
					i++;
				}
			}
			tokens.push({
				type: 2,
				name,
				modifier,
				nextLiteral: void 0
			});
			continue;
		}
		let hasEscape = false;
		const start = i;
		while (i < length) {
			const charCode = pattern.charCodeAt(i);
			if (charCode === BACKSLASH && i + 1 < length) {
				hasEscape = true;
				i += 2;
				continue;
			}
			if (charCode === OPEN_BRACKET) {
				inBrackets = true;
				i++;
				continue;
			}
			if (charCode === CLOSE_BRACKET) {
				inBrackets = false;
				i++;
				continue;
			}
			if (charCode === ASTERISK && !inBrackets) break;
			if (charCode === COLON && !inBrackets && i + 1 < length && isIdentStartCode(pattern.charCodeAt(i + 1))) break;
			i++;
		}
		if (hasEscape) {
			let value = "";
			for (let j = start; j < i; j++) {
				if (pattern.charCodeAt(j) === BACKSLASH && j + 1 < i) j++;
				value += pattern[j];
			}
			tokens.push({
				type: 0,
				value
			});
		} else tokens.push({
			type: 0,
			value: pattern.slice(start, i)
		});
	}
	let lastLiteral;
	for (let j = tokens.length - 1; j >= 0; j--) {
		const token = tokens[j];
		if (token.type === 0) lastLiteral = token.value;
		else token.nextLiteral = lastLiteral;
	}
	return tokens;
}
/**
* Try to match a decoded literal against an encoded input segment.
* Returns the number of raw input characters consumed, or -1 on failure.
*/
function findEncodedLiteralEnd(input, position, literal) {
	const maxLength = Math.min(input.length - position, literal.length * 3);
	for (let length = literal.length; length <= maxLength; length++) {
		const segment = input.slice(position, position + length);
		const decoded = decode(segment);
		if (decoded === literal) return length;
		if (decoded.length > literal.length && decoded !== segment) return -1;
	}
	return -1;
}
let matcherInput = "";
let matcherInputLength = 0;
let matcherTokens = [];
let matcherTokenCount = 0;
let matcherTolerateTrailingSlash = false;
let matcherParams;
let matcherRemainingSteps = 0;
let matcherFailedStates;
const matcherBoundTokens = [];
const matcherBoundStarts = [];
const matcherBoundEnds = [];
function finalizeMatch() {
	const params = Object.create(null);
	let wildcardIndex = 0;
	for (let i = 0; i < matcherBoundTokens.length; i++) {
		const token = matcherBoundTokens[i];
		const start = matcherBoundStarts[i];
		const end = matcherBoundEnds[i];
		if (token.type === 1) {
			if (start !== end) params[String(wildcardIndex)] = decode(matcherInput.slice(start, end));
			wildcardIndex++;
			continue;
		}
		if (token.type !== 2 || start === end) continue;
		const captured = decode(matcherInput.slice(start, end));
		const existing = params[token.name];
		if (existing === void 0) params[token.name] = captured;
		else if (Array.isArray(existing)) existing.push(captured);
		else params[token.name] = [existing, captured];
	}
	matcherParams = params;
	return true;
}
function bindAndContinue(token, tokenIndex, start, end) {
	matcherBoundTokens.push(token);
	matcherBoundStarts.push(start);
	matcherBoundEnds.push(end);
	if (matchFrom(tokenIndex + 1, end)) return true;
	matcherBoundTokens.pop();
	matcherBoundStarts.pop();
	matcherBoundEnds.pop();
	return false;
}
function matchLiteral(token, tokenIndex, position) {
	const value = token.value;
	if (matcherInput.startsWith(value, position)) {
		if (matchFrom(tokenIndex + 1, position + value.length)) return true;
	} else if (matcherInput.indexOf("%", position) !== -1) {
		const encodedLength = findEncodedLiteralEnd(matcherInput, position, value);
		if (encodedLength !== -1 && matchFrom(tokenIndex + 1, position + encodedLength)) return true;
	}
	if (value.length > 0 && value.charCodeAt(value.length - 1) === SLASH && tokenIndex + 1 < matcherTokenCount) {
		const nextToken = matcherTokens[tokenIndex + 1];
		if (nextToken.type === 2 && (nextToken.modifier === "?" || nextToken.modifier === "*")) {
			const trimmedValue = value.slice(0, -1);
			if (matcherInput.startsWith(trimmedValue, position) && matchFrom(tokenIndex + 2, position + trimmedValue.length)) return true;
		}
	}
	return false;
}
function matchParamOrWildcard(token, tokenIndex, position) {
	const nextLiteralValue = token.nextLiteral;
	const isSegmentScoped = token.type === 2 && token.modifier !== "+" && token.modifier !== "*";
	const allowEmpty = token.type === 1 || token.modifier === "?" || token.modifier === "*";
	let boundary;
	if (isSegmentScoped) {
		const slashIndex = matcherInput.indexOf("/", position);
		boundary = slashIndex === -1 ? matcherInputLength : slashIndex;
	} else boundary = matcherInputLength;
	if (nextLiteralValue === void 0) {
		if (tokenIndex === matcherTokenCount - 1) {
			if (!allowEmpty && position === boundary) return false;
			if (token.type === 2 && !isSegmentScoped && matcherTolerateTrailingSlash && boundary > position && matcherInput.charCodeAt(boundary - 1) === SLASH && (allowEmpty || boundary - 1 > position) && bindAndContinue(token, tokenIndex, position, boundary - 1)) return true;
			return bindAndContinue(token, tokenIndex, position, boundary);
		}
		for (let end = position; end <= boundary; end++) {
			if (!allowEmpty && end === position) continue;
			if (bindAndContinue(token, tokenIndex, position, end)) return true;
		}
		return false;
	}
	let searchFrom = position;
	let triedEmptyCapture = false;
	while (true) {
		const occurrenceIndex = matcherInput.indexOf(nextLiteralValue, searchFrom);
		if (occurrenceIndex === -1 || occurrenceIndex > boundary) break;
		if (occurrenceIndex === position) triedEmptyCapture = true;
		if (allowEmpty || occurrenceIndex !== position) {
			if (bindAndContinue(token, tokenIndex, position, occurrenceIndex)) return true;
		}
		searchFrom = occurrenceIndex + 1;
	}
	if (allowEmpty && !triedEmptyCapture) return bindAndContinue(token, tokenIndex, position, position);
	return false;
}
function matchFrom(tokenIndex, position) {
	if (matcherRemainingSteps === 0) return false;
	matcherRemainingSteps--;
	if (tokenIndex === matcherTokenCount) {
		const unconsumed = matcherInputLength - position;
		if (unconsumed === 0 || matcherTolerateTrailingSlash && unconsumed === 1 && matcherInput.charCodeAt(position) === SLASH) return finalizeMatch();
		return false;
	}
	const stateKey = tokenIndex * (matcherInputLength + 1) + position;
	if (matcherFailedStates !== void 0 && matcherFailedStates.has(stateKey)) return false;
	const token = matcherTokens[tokenIndex];
	const matched = token.type === 0 ? matchLiteral(token, tokenIndex, position) : matchParamOrWildcard(token, tokenIndex, position);
	if (!matched) {
		if (matcherFailedStates === void 0) matcherFailedStates = /* @__PURE__ */ new Set();
		matcherFailedStates.add(stateKey);
	}
	return matched;
}
/**
* Single linear pass that binds every wildcard/param to the same first
* candidate the backtracking matcher would try. Returns a MatchResult
* when it can conclude on its own, or `undefined` when it failed past
* a point where untried alternatives exist and backtracking is needed.
*/
function matchTokensLinear(inputString, tokens, tolerateTrailingSlash) {
	const inputLength = inputString.length;
	const totalTokens = tokens.length;
	let position = 0;
	let wildcardIndex = 0;
	let hasAlternatives = false;
	const params = Object.create(null);
	for (let i = 0; i < totalTokens; i++) {
		const token = tokens[i];
		if (token.type === 0) {
			const value = token.value;
			let hasTrimAlternative = false;
			if (value.charCodeAt(value.length - 1) === SLASH && i + 1 < totalTokens) {
				const nextToken = tokens[i + 1];
				hasTrimAlternative = nextToken.type === 2 && (nextToken.modifier === "?" || nextToken.modifier === "*");
			}
			if (inputString.startsWith(value, position)) {
				if (hasTrimAlternative) hasAlternatives = true;
				position += value.length;
				continue;
			}
			if (inputString.indexOf("%", position) !== -1) {
				const encodedLength = findEncodedLiteralEnd(inputString, position, value);
				if (encodedLength !== -1) {
					if (hasTrimAlternative) hasAlternatives = true;
					position += encodedLength;
					continue;
				}
			}
			if (hasTrimAlternative) {
				const trimmedValue = value.slice(0, -1);
				if (inputString.startsWith(trimmedValue, position)) {
					position += trimmedValue.length;
					i++;
					continue;
				}
			}
			return hasAlternatives ? void 0 : NO_MATCH;
		}
		const nextLiteralValue = token.nextLiteral;
		const isSegmentScoped = token.type === 2 && token.modifier !== "+" && token.modifier !== "*";
		const allowEmpty = token.type === 1 || token.modifier === "?" || token.modifier === "*";
		let boundary;
		if (isSegmentScoped) {
			const slashIndex = inputString.indexOf("/", position);
			boundary = slashIndex === -1 ? inputLength : slashIndex;
		} else boundary = inputLength;
		let endPosition;
		if (nextLiteralValue === void 0) if (i === totalTokens - 1) {
			if (!allowEmpty && position === boundary) return hasAlternatives ? void 0 : NO_MATCH;
			endPosition = boundary;
			if (token.type === 2 && !isSegmentScoped && tolerateTrailingSlash && boundary > position && inputString.charCodeAt(boundary - 1) === SLASH && (allowEmpty || boundary - 1 > position)) {
				endPosition = boundary - 1;
				hasAlternatives = true;
			}
		} else {
			endPosition = allowEmpty ? position : position + 1;
			if (endPosition > boundary) return hasAlternatives ? void 0 : NO_MATCH;
			if (endPosition < boundary) hasAlternatives = true;
		}
		else {
			let occurrenceIndex = inputString.indexOf(nextLiteralValue, position);
			if (!allowEmpty && occurrenceIndex === position) occurrenceIndex = inputString.indexOf(nextLiteralValue, position + 1);
			if (occurrenceIndex === -1 || occurrenceIndex > boundary) {
				if (!allowEmpty) return hasAlternatives ? void 0 : NO_MATCH;
				endPosition = position;
			} else {
				endPosition = occurrenceIndex;
				hasAlternatives = true;
			}
		}
		if (token.type === 1) {
			if (position !== endPosition) params[String(wildcardIndex)] = decode(inputString.slice(position, endPosition));
			wildcardIndex++;
		} else if (position !== endPosition) {
			const captured = decode(inputString.slice(position, endPosition));
			const existing = params[token.name];
			if (existing === void 0) params[token.name] = captured;
			else if (Array.isArray(existing)) existing.push(captured);
			else params[token.name] = [existing, captured];
		}
		position = endPosition;
	}
	const unconsumed = inputLength - position;
	if (unconsumed !== 0 && !(tolerateTrailingSlash && unconsumed === 1 && inputString.charCodeAt(position) === SLASH)) return hasAlternatives ? void 0 : NO_MATCH;
	return {
		matches: true,
		params
	};
}
function matchTokens(inputString, tokens, tolerateTrailingSlash) {
	const linearResult = matchTokensLinear(inputString, tokens, tolerateTrailingSlash);
	if (linearResult !== void 0) return linearResult;
	matcherInput = inputString;
	matcherInputLength = inputString.length;
	matcherTokens = tokens;
	matcherTokenCount = tokens.length;
	matcherTolerateTrailingSlash = tolerateTrailingSlash;
	matcherParams = void 0;
	matcherRemainingSteps = MAX_MATCH_STEPS;
	matcherFailedStates = void 0;
	matcherBoundTokens.length = 0;
	matcherBoundStarts.length = 0;
	matcherBoundEnds.length = 0;
	matchFrom(0, 0);
	if (matcherParams === void 0) return NO_MATCH;
	return {
		matches: true,
		params: matcherParams
	};
}
function removeQueryAndFragment(input) {
	const hashIndex = input.indexOf("#");
	if (hashIndex !== -1) input = input.slice(0, hashIndex);
	const queryIndex = input.indexOf("?");
	return queryIndex === -1 ? input : input.slice(0, queryIndex);
}
function removeTrailingSlash(input) {
	if (input.length > 1 && input.charCodeAt(input.length - 1) === SLASH) return input.slice(0, -1);
	return input;
}
function decode(value) {
	if (value.indexOf("%") === -1) return value;
	try {
		return decodeURIComponent(value);
	} catch {
		return value;
	}
}
/**
* Match a URL against the given pattern.
* @example
* matchPattern('http://localhost/user/:userId', 'http://localhost/user/123')
* // { matches: true, params: { userId: '123' } }
*/
function matchPattern(pattern, input) {
	const rawInput = typeof input === "string" ? input : input.href;
	if (rawInput.length > MAX_INPUT_LENGTH) throw new Error(`matchPattern: input URL exceeds the maximum allowed length of ${MAX_INPUT_LENGTH} characters (received ${rawInput.length}).`);
	const inputString = lowercaseSchemeAndHost(removeQueryAndFragment(rawInput));
	const { tokens, isLiteralOnly, hasTrailingSlash, normalizedPattern } = parsePatternOrGetFromCache(pattern);
	if (isLiteralOnly) {
		if (inputString === normalizedPattern || decode(inputString) === normalizedPattern) return {
			matches: true,
			params: Object.create(null)
		};
		if (!hasTrailingSlash) {
			const stripped = removeTrailingSlash(inputString);
			if (stripped === normalizedPattern || decode(stripped) === normalizedPattern) return {
				matches: true,
				params: Object.create(null)
			};
		}
		return NO_MATCH;
	}
	return matchTokens(inputString, tokens, !hasTrailingSlash);
}
//#endregion
export { matchPattern };
