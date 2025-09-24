import os
import sys
import time

if os.getenv("CONVERT_NO_JITTER", "0") == "1":
    _orig_sleep = time.sleep

    def _nop_sleep(seconds=0):
        try:
            sec = float(seconds)
        except Exception:
            sec = 0
        if sec > 0:
            sys.stderr.write(
                "NO_JITTER: intercepted time.sleep({:.2f}) -> 0s\n".format(sec)
            )
            sys.stderr.flush()
            return
        return _orig_sleep(seconds)

    time.sleep = _nop_sleep
