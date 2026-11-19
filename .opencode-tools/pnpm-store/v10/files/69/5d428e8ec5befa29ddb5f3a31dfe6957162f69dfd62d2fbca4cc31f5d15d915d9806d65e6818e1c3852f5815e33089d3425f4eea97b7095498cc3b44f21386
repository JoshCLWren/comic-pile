"use strict";

const enumerationValues = new Set([
  "text/html",
  "text/xml",
  "application/xml",
  "application/xhtml+xml",
  "image/svg+xml",
]);
exports.enumerationValues = enumerationValues;

exports.convert = (globalObject, value, { context = "The provided value" } = {}) => {
  const string = `${value}`;
  if (!enumerationValues.has(string)) {
    throw new globalObject.TypeError(
      `${context} must be one of: "text/html", "text/xml", "application/xml", "application/xhtml+xml", "image/svg+xml". Received: ${JSON.stringify(string)}.`,
    );
  }
  return string;
};
