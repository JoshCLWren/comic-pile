"use strict";

const enumerationValues = new Set(["loading", "interactive", "complete"]);
exports.enumerationValues = enumerationValues;

exports.convert = (globalObject, value, { context = "The provided value" } = {}) => {
  const string = `${value}`;
  if (!enumerationValues.has(string)) {
    throw new globalObject.TypeError(
      `${context} must be one of: "loading", "interactive", "complete". Received: ${JSON.stringify(string)}.`,
    );
  }
  return string;
};
