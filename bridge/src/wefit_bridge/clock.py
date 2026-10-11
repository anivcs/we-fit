"""The one clock the bridge uses for `now` and for arrival stamps.

time.monotonic ticks every 15.6 ms on Windows before Python 3.13, which is too coarse
to time 50 Hz samples. perf_counter is sub-microsecond everywhere.
"""

import time

now = time.perf_counter
