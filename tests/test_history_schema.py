import jsonschema

schema = {
    "type": "object",
    "properties": {
        "quoteId": {"type": "string"},
        "orderId": {"type": ["string", "null"]},
        "createTime": {"type": ["number", "null"]},
        "validTime": {"type": ["number", "null"]},
        "from_token": {"type": "string"},
        "to_token": {"type": "string"},
        "fromAmount": {"type": ["number", "null"]},
        "toAmount": {"type": ["number", "null"]},
        "ratio": {"type": ["number", "null"]},
        "inverseRatio": {"type": ["number", "null"]},
        "expected_profit": {"type": ["number", "null"]},
        "prob_up": {"type": ["number", "null"]},
        "score": {"type": ["number", "null"]},
        "accepted": {"type": "boolean"},
        "dryRun": {"type": "boolean"},
        "error": {},
        "timestamp": {"type": "string"},
    },
    "required": [
        "quoteId",
        "from_token",
        "to_token",
        "fromAmount",
        "toAmount",
        "ratio",
        "inverseRatio",
        "expected_profit",
        "prob_up",
        "score",
        "accepted",
        "dryRun",
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
        "createTime": 1,
        "validTime": 2,
        "from_token": "A",
        "to_token": "B",
        "fromAmount": 1.0,
        "toAmount": 1.0,
        "ratio": 1.0,
        "inverseRatio": 1.0,
        "expected_profit": 0.1,
        "prob_up": 0.5,
        "score": 0.05,
        "accepted": True,
        "dryRun": False,
        "error": None,
        "timestamp": "2024-01-01T00:00:00",
    }
    jsonschema.validate(record, schema)


def test_schema_reject_without_order():
    record = {
        "quoteId": "1",
        "orderId": None,
        "createTime": None,
        "validTime": None,
        "from_token": "A",
        "to_token": "B",
        "fromAmount": 1.0,
        "toAmount": 1.0,
        "ratio": 1.0,
        "inverseRatio": 1.0,
        "expected_profit": 0.1,
        "prob_up": 0.5,
        "score": 0.05,
        "accepted": False,
        "dryRun": True,
        "error": {"code": -1},
        "timestamp": "2024-01-01T00:00:00",
    }
    jsonschema.validate(record, schema)
