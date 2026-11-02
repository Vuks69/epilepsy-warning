# Optimization Plan (GIF-focused)

## Context
- Primary use case: animated GIFs (local files/bytes). Videos are less common.
- Current state: added `sample_fps` default 15.0 with `no_downsample` flag (video-focused, no effect on GIFs). 
- Profiles: WCAG 2.2 SC 2.3.1, rule-based detection. Must remain standards-explicit.
- Constraints from AGENTS.md: don't change detector semantics silently, keep assumptions/warnings, tile_grid_max must remain high enough to not miss flashes (coarse grids averaged away fine patterns as seen with 1.gif).

## Bottlenecks (from profiling)
Based on line_profiler/cProfile on video; for GIFs focus shifts:
| Area | Cost (GIFs) | Notes |
|---|---|---|
| GIF decoding/compositing | High | `_pillow_frames` does `Image.seek`, `alpha_composite` per frame, disposal handling, canvas copies. For short looping GIFs we also expand cycles. |
| Tiling/resizing | High | `tile_frame` does `Image.fromarray` + `Image.resize` (BOX) per frame. Scales with source pixels and tile grid. |
| Color transforms | Medium-High | `srgb_to_linear` uses `** 2.4` (np.power), `linear_rgb_to_xyz`/`linear_rgb_to_ucs` create copies/stacks. |
| Engine loops | Medium | Suffix scans, per-tile boolean ops; usually less dominant than decode/tile for GIFs. |
| Area evaluation | Low-Medium | Sliding window sums cheap relative to decode. |

## Optimization opportunities (GIF-prioritized)

### 1) GIF decode/compositing (highest impact for GIFs)
| Optimization | Effort | Impact | Risk | Notes |
|---|---|---|---|---|
| Avoid unnecessary conversions | S | High | Low | In `_pillow_frames`, we do `canvas.convert("RGBA")` then composite then `canvas.convert("RGB")`. Can track in RGBA longer or avoid double-converts where possible. Also disposal copies (`canvas.copy()`) add up. |
| Optimize canvas management | S | High | Low | Use numpy arrays for compositing when possible (avoid PIL object churn). Or reuse buffers. Disposal handling is correct per spec (must match browser behavior) - don't shortcut. |
| Faster disposal logic | S | Med-High | Med | Current logic is correct (disposal 2 restores background, disposal 3 restores previous). Need to be careful not to break compositing. |
| Skip work for static/opaque GIFs | S | Med-High | Low | Detect transparency/opaqueness early; if fully opaque and no disposal complexity, can simplify path. |
| Reduce frame copies | S | Med-High | Low | `first_frame.copy()` stored for loop wrap; `restore = canvas.copy()` for disposal 3. Some copies unavoidable for correctness. |

### 2) Tiling/resizing (high impact)
| Optimization | Effort | Impact | Risk | Notes |
|---|---|---|---|---|
| Numpy box downsample | M | High | Low | Replace `Image.fromarray` + `Image.resize(BOX)` with stride-based averaging in numpy. Avoids PIL ImagingCore allocations per frame. Keep behavior equivalent (box filter). |
| LRU/reuse of PIL images | S | Med-High | Low | Reuse image objects where possible. |
| Smarter tile_grid_max defaults | S | Med | Med | For very small GIFs we already clamp thresholds; don't drop below safe minimum. Current default 192 is safe. Consider per-dimension heuristic but must not sacrifice detection. |
| Handle RGBA path efficiently | S | Med | Low | For RGBA frames going to tile, can composite to RGB array directly without going through PIL `Image` objects as much. |

### 3) Color transforms (medium-high impact)
| Optimization | Effort | Impact | Risk | Notes |
|---|---|---|---|---|
| sRGB->linear LUT | S | High | Low | Build 256-entry LUT once at module load: `lut[i] = linear value for uint8 i`. Index into LUT. Much faster than `**2.4`. Must be exact enough for thresholds (float32 precision fine). |
| Fuse transforms | M | Med-High | Low | Compute luminance, red_ratio, and XYZ/UCS in one pass to reduce array lookups/copies. Avoid recomputing linear RGB multiple times. |
| Avoid np.stack copies | S | Med | Low | In `linear_rgb_to_xyz`, write to pre-allocated arrays or restructure to avoid `np.stack`. |
| Precompute constants | S | Low | Low | Minor, constants already exist. |

### 4) Engine/area (smaller gains, correctness-sensitive)
| Optimization | Effort | Impact | Risk | Notes |
|---|---|---|---|---|
| Incremental suffix min/max in `_detect_luminance` | M | Med | Med | History window is small (66ms) but we recompute from scratch each frame. Need to be careful about correctness. |
| Short-circuit in `_detect_red` | M | Med | Med | Skip tiles that can't qualify early. Must preserve exact logic. |
| Cache area evaluations | M | Med | Med | Some mask unions repeat. Need identity checks. |
| Avoid `pop(0)` on history list | S | Low | Low | Use `collections.deque` or index; history tiny. |

## Implementation plan

### Phase 1: Quick wins (low risk, good for GIFs)
1. **sRGB->linear LUT** in `color.py` - replace `np.where` + power with LUT indexing. Add `@lru_cache` or module-level array.
2. **Optimize `tile_frame` allocations** - try to avoid some PIL object creation; test numpy box downsample.
3. **Reduce copies in GIF compositing** - audit `_pillow_frames` for unnecessary `.copy()` calls.

### Phase 2: Medium effort (GIF-focused)
1. **Numpy box downsample** implementation - replace PIL resize path, keep fallback or flag.
2. **Fuse color transforms** in engine to cut passes.
3. **Optimize canvas compositing** - use numpy arrays where feasible.

Status: implemented in 0.2.x.
1. `area.py` has an exact numpy BOX implementation (Pillow-compatible fixed-point coefficients, prefix-sum axis passes) but it is used as a fallback, not the normal path: benchmarking showed Pillow's C resize is roughly 5-8x faster for real downscales inside this pipeline. `tile_frame_uint8` exposes the uint8 tile averages without a float round-trip; `tile_frame` remains the public float wrapper.
2. `color.py` exposes `linear_rgb_features`, which computes luminance, redness, the saturated-red mask, and CIE UCS in one pass; `engine.py` uses it. The sRGB LUT now matches the float32 path exactly.
3. `decode.py` keeps an RGBA numpy canvas and vectorizes Pillow's `AlphaComposite.c` integer formula. Opaque and fully transparent sources take cheap paths; disposal semantics are unchanged.
   Results matched the captured baseline for the benchmark set; GIF timings improved modestly. No detector semantics, warnings, assumptions, or the `tile_grid_max` default changed.

### Phase 3: Algorithmic (careful testing)
Status: not started. Unlike phases 1-2 these change the shape of the per-frame computation; the acceptance bar is bit-identical events, not just identical smoke-fixture output. Only pursue if a profile after phases 1-2 shows the engine is a material share of runtime; decode and tiling dominate GIFs.

1. **Incremental suffix min/max in `_detect_luminance`**
   - What it means: for every history record the engine needs the min and max luminance of that record *and every newer record still in the 66 ms window* (`suffix_min`/`suffix_max` in `engine.py`). Those arrays define the local-extremum test that identifies where a transition started. Today `add_frame` appends one record, prunes the window, then rebuilds the whole suffix structure from scratch with two fresh arrays per history entry.
   - The idea: keep the suffix state as a rolling structure tied to the sliding window and update it on append/prune instead of rescanning, avoiding per-frame allocation and Python loop overhead.
   - Caveat: the window is short, so the history is tiny (about 2 records at 15 fps, up to roughly 7 for a 10 ms GIF delay). There is no real asymptotics win; appending a frame can invalidate every earlier suffix value, so "incremental" mainly means rolling buffers and less copying, and the payoff is modest.
   - Must preserve: the coarse-step rule (`step_index` / `step_is_coarse`, which reports an unresolved single-frame step as `duration_ms=0`), and the pruning rule that keeps at least two records so the earliest can serve as `previous` for the next one. Suffix extrema for in-window indices only look at newer records, so the out-of-window reference record does not widen the extremum window.

2. **Engine short-circuiting**
   - Goal: skip work that provably cannot affect the result. Safe candidates, roughly highest value first:
     - **Whole-detector red guard.** `_detect_red` computes UCS distances for every history record before applying `(record.red | now.red)`. If neither the current frame nor any history record has a saturated-red tile, `valid` is all-false by construction, so an early return is exactly semantics-preserving. Most ordinary content takes this path.
     - **Per-record red candidate check.** Apply the same mask before computing the distance (`if not (record.red | now.red).any(): continue`). Whether this beats whole-grid vectorization depends on mask sparsity; benchmark instead of assuming.
     - **Window-range prefilter in `_detect_luminance`.** A tile whose window-wide range (`suffix_max[0] - suffix_min[0]`) is too small can be excluded. The safe bound is model-dependent: under `wcag_relative` the SDR threshold is the bound, but under `cd_m2` the HDR Michelson branch can qualify a pair whose absolute difference is below `threshold * reference` (with `low >= 0.8 * reference` it needs at least `1.6 / 17` of relative luminance), so the prefilter must use the smaller of the SDR and HDR bounds. Getting this wrong silently drops real HDR flashes. Also requires moving from whole-grid ops to indexed ops, and fancy-indexing overhead can exceed the savings on dense frames. Risky.
     - **Duplicate-frame skip.** If the new tile grid is elementwise identical to the previous record, all differences are zero and neither detector can fire. The record must still be appended (it changes future windows), but the per-frame detection pass can be skipped. The grid is small (192 x 192 x 3), and repeated GIF frames are common.
     - **Area evaluation cache.** `AreaEvaluator.evaluate` is called repeatedly for the same or overlapping masks (candidates, synchronized flush, `_alternating` coalescing, flash union). Memoizing on mask identity/hash is a related win.
   - Must not do: abort a file once the 7-transitions-per-second limit is exceeded. That shortens triggering media but changes reported measurements (`max_area`, `max_transition_duration_ms`, event counts, fast-flash merging) and the meaning of a full-file scan. The intent is skipping irrelevant work, not early verdicts.

Considerations:
- Verify with an equivalence test, not just the smoke fixtures: run the optimized detector and a reference implementation over randomized synthetic histories that cover exactly-at-threshold values, the local-extremum tolerance boundary, red tie-breaking, and the coarse-step path, and assert identical events and measurements.
- Re-profile before and after each item; the engine loops are vectorized across tiles already, so small-history assumptions may not hold at high frame rates.
- Keep changes independently revertible, one idea per commit, so a benchmark regression can be attributed.

## Testing strategy
- Always run unit tests: `.venv/bin/python -m unittest discover -s tests -v`
- Run smoke tests: `epilepsy-scan examples/triggering/1.gif` (must exit 1, triggering), `epilepsy-scan examples/triggering/4882.mp4` (with default 15fps sampling), and all `examples/not-triggering/*.gif` (must exit 0)
- Benchmark GIFs: measure time for triggering GIFs and representative benign GIFs
- Compare results (risk/reasons/measurements) against baseline for correctness
- Profile with line_profiler/cProfile after changes

## Notes
- GIFs are the primary use case - prioritize decode/compositing and tiling over video-specific optimizations.
- 15 fps default sampling is correct for videos but irrelevant for GIFs; keeping it is fine.
- Tile grid default of 192 must remain (lowering breaks detection as shown).
- All optimizations must preserve warnings/assumptions and standards-explicit behavior.
