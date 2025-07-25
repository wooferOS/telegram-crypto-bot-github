import collections

from convert_model import prepare_dataset


def test_prepare_dataset_preserves_executed():
    history = []
    for i in range(20):
        history.append({
            "expected_profit": 0.1,
            "accepted": True,
            "executed": i != 0,
            "ratio": 1.1,
            "inverseRatio": 0.9,
            "amount": 10.0,
            "from_token": "AAA",
            "to_token": "BBB",
        })

    prepared = prepare_dataset(history)
    counts = collections.Counter(item["executed"] for item in prepared)
    assert counts[True] == 19 and counts[False] == 1
