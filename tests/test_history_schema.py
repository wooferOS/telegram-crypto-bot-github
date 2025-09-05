import jsonschema

schema = {
    "type": "object",
    "properties": {
        "createTime": {"type": ["number", "null"]},
        "region": {"type": ["string", "null"]},
        "quoteId": {"type": "string"},
        "fromAsset": {"type": "string"},
        "toAsset": {"type": "string"},
        "fromAmount": {"type": ["string", "null"]},
        "toAmount": {"type": ["string", "null"]},
        "ratio": {"type": ["string", "null"]},
        "inverseRatio": {"type": ["string", "null"]},
        "validUntil": {"type": ["number", "null"]},
        "accepted": {"type": "boolean"},
        "orderId": {"type": ["string", "null"]},
        "orderStatus": {"type": ["string", "null"]},
        "error": {},
        "dryRun": {"type": "boolean"},
        "edge": {"type": ["number", "null"]},
        "mode": {"type": ["string", "null"]},
        "timestamp": {"type": ["string", "null"]},
    },
    "required": [
        "quoteId",
        "fromAsset",
        "toAsset",
        "fromAmount",
        "toAmount",
        "ratio",
        "inverseRatio",
        "accepted",
        "dryRun",
        "mode",
    ],
    "allOf": [
        {
            "if": {"properties": {"accepted": {"const": True}}},
            "then": {"required": ["orderId", "orderStatus"]},
        }
    ],
}


def test_schema_accept_with_order():
    record = {
        "createTime": 1,
        "region": "ASIA",
        "quoteId": "1",
        "fromAsset": "A",
        "toAsset": "B",
        "fromAmount": "1.0",
        "toAmount": "1.0",
        "ratio": "1.0",
        "inverseRatio": "1.0",
        "validUntil": 2,
        "accepted": True,
        "orderId": "10",
        "orderStatus": "SUCCESS",
        "error": None,
        "dryRun": False,
        "edge": 0.1,
        "mode": "live",
    }
    jsonschema.validate(record, schema)


def test_schema_reject_without_order():
    record = {
        "createTime": None,
        "region": "ASIA",
        "quoteId": "1",
        "fromAsset": "A",
        "toAsset": "B",
        "fromAmount": "1.0",
        "toAmount": "1.0",
        "ratio": "1.0",
        "inverseRatio": "1.0",
        "validUntil": None,
        "accepted": False,
        "orderId": None,
        "orderStatus": None,
        "error": {"code": -1},
        "dryRun": True,
        "edge": None,
        "mode": "paper",
    }
    jsonschema.validate(record, schema)
