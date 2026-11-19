"use strict";

const enumerationValues = new Set(["start", "center", "end", "nearest"]);
exports.enumerationValues = enumerationValues;

exports.convert = (globalObject, value, { context = "The provided value" } = {}) => {
  const string = `${value}`;
  if (!enumerationValues.has(string)) {
    throw new globalObject.TypeError(
      `${context} must be one of: "start", "center", "end", "nearest". Received: ${JSON.stringify(string)}.`,
    );
  }
  return string;
};
