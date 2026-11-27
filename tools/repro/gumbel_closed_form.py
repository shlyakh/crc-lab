# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-framework==1.1.0", "numpy"]
# ///
import json
import numpy as np
from crc_framework import DistributionFamily, QuantileCurve, QuantileFit, fit_quantiles
T = np.array([10, 20, 50, 75, 100, 200, 500.0]); p = 1 - 1 / T; y = -np.log(-np.log(p))
spec = QuantileFit(family=DistributionFamily.GUMBEL_RIGHT)
for depths in ((1, 1, 1, 1, 1, 2.639, 3.768), (1, 1, 1, 1, 1, 1.016, 1.13)):
    for kind, v in (("float32", [float(np.float32(d)) for d in depths]), ("decimal", [float(d) for d in depths])):
        beta, mu = np.polyfit(y, v, 1)
        sse = float(np.sum((mu + beta * y - np.array(v)) ** 2))
        try:
            f = fit_quantiles(QuantileCurve(list(p), v), spec)
            rec = json.loads(f.record.to_json())
            att = rec["attempts"][rec["selected_attempt"]]
            res = json.dumps({k: att[k] for k in att if k != "diagnostic"})[:300]
        except Exception as e:
            res = f"{type(e).__name__}"
        print(f"{depths[-2:]} {kind}: closed form loc={mu:.6f} scale={beta:.6f} sse={sse:.6g} | framework: {res}")
