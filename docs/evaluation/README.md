# Reproducible detector evaluation

The committed manifest and summary are the compact outputs of:

```powershell
python -m backend.experiments.runner --output runtime/experiments/mall-final --repetitions 30 --seeds 11 29 47 71 101 --temporal-epochs 80
```

This is an offline, allowlisted evaluation: 30 repetitions across five seeds
and 12 scenarios (1,800 scenario runs). Raw events, predictions, run rows and
all five checkpoints remain under `runtime/experiments/mall-final`.

Across all scenarios, the edge-frequency baseline measured 0.8462 recall,
1.0000 precision and 0.0000 false-positive rate. The temporal-graph engine
measured 0.9231 recall, 0.9231 precision and a 0.0910 false-positive rate. It
detected the vertical port-scan scenario at 1.0000 recall where the baseline
measured 0.0000 recall. These offline numbers do not measure live containment,
recovery time, or cluster overhead.
