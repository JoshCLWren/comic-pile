"use strict";

const enumerationValues = new Set(["auto", "manual"]);
exports.enumerationValues = enumerationValues;

exports.convert = (globalObject, value, { context = "The provided value" } = {}) => {
  const string = `${value}`;
  if (!enumerationValues.has(string)) {
    throw new globalObject.TypeError(
      `${context} must be one of: "auto", "manual". Received: ${JSON.stringify(string)}.`,
    );
  }
  return string;
};
