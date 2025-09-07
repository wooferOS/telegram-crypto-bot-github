import logging
import convert_logger

def test_log_format(caplog):
    quote = {
        'quoteId': 'q1',
        'fromAsset': 'A',
        'toAsset': 'B',
        'fromAmount': '1',
        'toAmount': '2',
    }
    with caplog.at_level(logging.INFO, logger='convert'):
        convert_logger.log_conversion_result(
            quote,
            True,
            order_id='123',
            error=None,
            create_time=1,
            order_status={'orderStatus': 'SUCCESS'},
            edge=0.1,
        )
    assert any(
        'quoteId=q1 -> accept ✅ -> orderId=123 -> status=SUCCESS' in m
        for m in caplog.messages
    )
