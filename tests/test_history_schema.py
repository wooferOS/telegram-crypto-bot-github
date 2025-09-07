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
        "edge": {"type": ["number", "null"]},
        "timestamp": {"type": ["string", "null"]},
    },
    "required": [
        "quoteId",
        "fromAsset",
        "toAsset",
        "fromAmount",
        "toAmount",
        "orderStatus",
        "accepted",
        "region",
        "createTime",
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
        "edge": 0.1,
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
        "edge": None,
    }
    jsonschema.validate(record, schema)
