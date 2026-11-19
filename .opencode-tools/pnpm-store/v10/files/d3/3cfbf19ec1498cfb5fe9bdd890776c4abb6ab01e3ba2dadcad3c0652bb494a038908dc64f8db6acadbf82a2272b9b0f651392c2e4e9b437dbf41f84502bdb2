"use strict";

const enumerationValues = new Set(["select", "start", "end", "preserve"]);
exports.enumerationValues = enumerationValues;

exports.convert = (globalObject, value, { context = "The provided value" } = {}) => {
  const string = `${value}`;
  if (!enumerationValues.has(string)) {
    throw new globalObject.TypeError(
      `${context} must be one of: "select", "start", "end", "preserve". Received: ${JSON.stringify(string)}.`,
    );
  }
  return string;
};
