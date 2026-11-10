# Fine-Control Protocol (2026.08)

`fine-control-2026-08` is a new benchmark protocol for higher-frequency,
fine-grained interaction. It is not a score-compatible maintenance update to the
paper protocol.

## Runtime contract

- Maximum agent steps per task: `400`.
- Configured action durations use the following mapping:

| Previous duration | Fine-control duration |
| ---: | ---: |
| 20 ms | 50 ms |
| 200 ms | 50 ms |
| 400 ms | 100 ms |
| 500 ms | 100 ms |
| 700 ms | 200 ms |
| 1000 ms | 200 ms |
| 2000 ms | 500 ms |

- The generic action fallback is `100 ms`; the generic typing fallback is
  `500 ms`.
- An action ends when its configured duration ends. No fixed post-action wait is
  added before pausing the game.

## Timing artifacts

Every interaction record contains `frame_timing` with:

- requested action duration and measured action wall time;
- wall-clock overshoot beyond the requested duration;
- pause-excluded real time and speed-scaled gameplay time for the frame;
- cumulative controlled time across frames; and
- the browser's cumulative pause-aware clocks.
