"""Dependency-free regression tests for the language-port contract oracle."""

from copy import deepcopy
import json
import unittest

from scripts.rust_endpoint_oracle import SqlTranscript, operation_contract, render


class EndpointOracleTests(unittest.TestCase):
    """Pin complete reference closure and prevent bind-value disclosure."""

    def schema(self) -> dict:
        """Return a contract with inherited auth, parameters and recursive models."""
        return {
            "openapi": "3.1.0",
            "security": [{"Bearer": []}],
            "paths": {"/example": {
                "parameters": [{"$ref": "#/components/parameters/Timezone"}],
                "get": {"responses": {"200": {"content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/Response"},
                }}}}},
            }},
            "components": {
                "securitySchemes": {"Bearer": {"type": "http", "scheme": "bearer"}},
                "parameters": {"Timezone": {"name": "timezone", "in": "query"}},
                "schemas": {
                    "Response": {"required": ["items"], "properties": {"items": {
                        "type": "array", "items": {"$ref": "#/components/schemas/Item"},
                    }}},
                    "Item": {"anyOf": [
                        {"type": "null"}, {"$ref": "#/components/schemas/Response"},
                    ]},
                    "Unrelated": {"type": "string"},
                },
            },
        }

    def test_closure_preserves_inherited_security_and_path_parameters(self) -> None:
        """Schema extraction retains every reachable definition without unrelated ones."""
        schema = self.schema()
        before = deepcopy(schema)
        result = json.loads(render(operation_contract(schema, "/example", "GET")))
        self.assertEqual(schema, before)
        self.assertEqual(set(result["components"]["schemas"]), {"Response", "Item"})
        self.assertIn("Bearer", result["components"]["securitySchemes"])
        self.assertIn("Timezone", result["components"]["parameters"])

    def test_nested_field_and_required_array_drift_changes_contract(self) -> None:
        """A nested field change cannot pass by comparing only the top-level response."""
        schema = self.schema()
        original = render(operation_contract(schema, "/example", "get"))
        schema["components"]["schemas"]["Item"]["anyOf"][0]["type"] = "string"
        self.assertNotEqual(original, render(operation_contract(schema, "/example", "get")))
        schema = self.schema()
        schema["components"]["schemas"]["Response"]["required"] = []
        self.assertNotEqual(original, render(operation_contract(schema, "/example", "get")))

    def test_explicit_anonymous_security_overrides_global_security(self) -> None:
        """An operation's empty security requirement remains meaningful."""
        schema = self.schema()
        schema["paths"]["/example"]["get"]["security"] = []
        result = json.loads(render(operation_contract(schema, "/example", "get")))
        self.assertNotIn("securitySchemes", result["components"])

    def test_missing_or_external_reference_fails_closed(self) -> None:
        """No missing reference may disappear silently from the frozen contract."""
        schema = self.schema()
        del schema["components"]["schemas"]["Item"]
        with self.assertRaises(KeyError):
            operation_contract(schema, "/example", "get")
        schema = self.schema()
        schema["components"]["schemas"]["Item"] = {"$ref": "https://example.invalid/schema"}
        with self.assertRaises(ValueError):
            operation_contract(schema, "/example", "get")

    def test_sql_trace_contains_order_and_types_but_no_bind_values(self) -> None:
        """Recording parameters must never serialize credentials or synthetic data."""
        transcript = SqlTranscript()
        connection = object()
        transcript.begin(connection)
        transcript.statement(connection, None, "SELECT $1::text, $2::int[]",
                             ("secret-do-not-export", [987654, 123456]), None, False)
        transcript.commit(connection)
        transcript.begin(connection)
        transcript.rollback(connection)
        text = render(transcript.events)
        self.assertNotIn("secret-do-not-export", text)
        self.assertNotIn("987654", text)
        self.assertEqual(transcript.events[1]["parameter_shape"], ["str", ["int", "int"]])
        self.assertEqual([item["event"] for item in transcript.events],
                         ["begin", "statement", "commit", "begin", "rollback"])


if __name__ == "__main__":
    unittest.main()
