import jsonschema

schema = {
    "type": "object",
    "properties": {
        "quoteId": {"type": "string"},
        "orderId": {"type": ["string", "null"]},
        "from_token": {"type": "string"},
        "to_token": {"type": "string"},
        "ratio": {"type": ["number", "null"]},
        "inverseRatio": {"type": ["number", "null"]},
        "from_amount": {"type": ["number", "null"]},
        "to_amount": {"type": ["number", "null"]},
        "score": {"type": ["number", "null"]},
        "expected_profit": {"type": ["number", "null"]},
        "prob_up": {"type": ["number", "null"]},
        "accepted": {"type": "boolean"},
        "error_code": {"type": ["number", "null"]},
        "error_msg": {"type": ["string", "null"]},
        "timestamp": {"type": "string"},
    },
    "required": [
        "quoteId",
        "from_token",
        "to_token",
        "ratio",
        "inverseRatio",
        "from_amount",
        "to_amount",
        "score",
        "expected_profit",
        "prob_up",
        "accepted",
        "timestamp",
    ],
    "allOf": [
        {
            "if": {"properties": {"accepted": {"const": True}}},
            "then": {"required": ["orderId"]},
        }
    ],
}


def test_schema_accept_with_order():
    record = {
        "quoteId": "1",
        "orderId": "10",
        "from_token": "A",
        "to_token": "B",
        "ratio": 1.0,
        "inverseRatio": 1.0,
        "from_amount": 1.0,
        "to_amount": 1.0,
        "score": 0.1,
        "expected_profit": 0.1,
        "prob_up": 0.5,
        "accepted": True,
        "error_code": None,
        "error_msg": None,
        "timestamp": "2024-01-01T00:00:00",
    }
    jsonschema.validate(record, schema)


def test_schema_reject_without_order():
    record = {
        "quoteId": "1",
        "orderId": None,
        "from_token": "A",
        "to_token": "B",
        "ratio": 1.0,
        "inverseRatio": 1.0,
        "from_amount": 1.0,
        "to_amount": 1.0,
        "score": 0.1,
        "expected_profit": 0.1,
        "prob_up": 0.5,
        "accepted": False,
        "error_code": -1,
        "error_msg": "err",
        "timestamp": "2024-01-01T00:00:00",
    }
    jsonschema.validate(record, schema)
