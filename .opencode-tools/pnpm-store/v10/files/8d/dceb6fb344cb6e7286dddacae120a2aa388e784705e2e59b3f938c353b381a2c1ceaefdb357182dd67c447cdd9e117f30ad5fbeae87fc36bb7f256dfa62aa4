"use strict";

const enumerationValues = new Set(["auto", "instant", "smooth"]);
exports.enumerationValues = enumerationValues;

exports.convert = (globalObject, value, { context = "The provided value" } = {}) => {
  const string = `${value}`;
  if (!enumerationValues.has(string)) {
    throw new globalObject.TypeError(
      `${context} must be one of: "auto", "instant", "smooth". Received: ${JSON.stringify(string)}.`,
    );
  }
  return string;
};
