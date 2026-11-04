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

## Status summary
At-a-glance. A checkmark is shipped and verified; a deferred item states *why* it is not done yet.

| Bucket | Status |
|---|---|
| Phase 1 — sRGB LUT, uint8 tiling, compositing audit | ✅ DONE (0.2.x) |
| Phase 2 — numpy BOX fallback, fused color, vectorized compositing | ✅ DONE (0.2.x) |
| Phase 3 — algorithmic engine short-circuits | 🟡 PARTIAL: 2 implemented, 4 deferred |
| Decode / compositing micro-opts | ⏳ DEFERRED |
| Tiling normal-path swap | ⏳ DEFERRED |
| Engine micro-opts (suffix min/max, red candidate check, window prefilter, area cache, deque history) | ⏳ DEFERRED |

Rationale for the ordering: the highest-impact buckets (decode/compositing, tiling) dominate GIF runtime but were intentionally deferred in favor of the safe, equivalence-preserving color/tiling work. The engine was only profiled *after* phases 1–2, and it is not a material share of GIF runtime — which is exactly why the riskier engine micro-opts (Phase 3) are deferred rather than shipped first.

## Optimization opportunities (GIF-prioritized)

### 1) GIF decode/compositing (highest impact for GIFs) — ⏳ DEFERRED
These touch browser-spec-critical compositing and disposal (disposal 2/3 restore background/previous frame; a wrong result fabricates full-screen flashes). The safe equivalent was shipped in Phase 2.3 instead: an RGBA numpy canvas that vectorizes Pillow's `AlphaComposite.c` formula, with cheap opaque/fully-transparent paths. The remaining micro-opts are low-risk but not benchmarked and lower priority than keeping the baseline correct — do them only if profiling shows a decode hotspot, one change per commit so a regression is attributable.
| Optimization | Effort | Impact | Risk | Status | Notes |
|---|---|---|---|---|---|
| Avoid unnecessary conversions | S | High | Low | ⏳ DEFERRED | `canvas.convert("RGBA")` → composite → `convert("RGB")` double-converts; track in RGBA longer where safe. |
| Optimize canvas management | S | High | Low | ✅ DONE (Phase 2) | RGBA numpy canvas; vectorized `AlphaComposite.c`. |
| Faster disposal logic | S | Med-High | Med | ⏳ DEFERRED | Current logic is correct (disposal 2 restores background, disposal 3 restores previous); do not shortcut without matching the browser. |
| Skip work for static/opaque GIFs | S | Med-High | Low | ⏳ DEFERRED | Detect transparency/opaqueness early; only simplify the path when disposal is inert. |
| Reduce frame copies | S | Med-High | Low | ⏳ DEFERRED | `first_frame.copy()` for loop wrap and disposal-3 `restore` copies are largely unavoidable for correctness. |

### 2) Tiling/resizing — ⏳ PARTIAL (fallback done; normal-path swap deferred)
| Optimization | Effort | Impact | Risk | Status | Reasoning |
|---|---|---|---|---|---|
| Numpy box downsample | M | High | Low | ✅ DONE **as a fallback only** | Implemented (`_box_downsample`, Pillow-compatible fixed-point coefficients, prefix-sum axis passes) but deliberately not the normal path: profiling showed Pillow's C resize is ~5-8x faster for real downscales in this pipeline. It exists for portability and as a tested bit-exact reference. Swapping it to default requires benchmarking first. |
| LRU/reuse of PIL images | S | Med-High | Low | ⏳ DEFERRED | Small GIF grids make PIL churn minor; no benchmark; low priority. |
| Smaller `tile_grid_max` defaults | S | Med | Med | ⏳ DEFERRED | Lowering it risks averaging away fine high-frequency patterns (detection regression, as with 1.gif). Default 192 must stay until a per-content heuristic is proven safe without dropping flashes. |
| Handle RGBA path efficiently | S | Med | Low | ⏳ DEFERRED | Minor; current RGBA→tile path is correct. Benchmark before changing. |

### 3) Color transforms (medium-high impact)
| Optimization | Effort | Impact | Risk | Status | Reasoning |
|---|---|---|---|---|---|
| sRGB→linear LUT | S | High | Low | ✅ DONE | 256-entry float32 LUT built once at module load; indexed, not `**2.4`. Matches the float path exactly. |
| Fuse transforms | M | Med-High | Low | ✅ DONE | `linear_rgb_features` computes luminance, redness, saturated-red mask, and CIE UCS in one pass. |
| Avoid `np.stack` copies | S | Med | Low | ⏳ DEFERRED | Minor allocation win; the fused path already computes everything in one pass, so this is low value. Defer. |
| Precompute constants | S | Low | Low | ✅ DONE | Constants already exist. |

### 4) Engine/area (smaller gains, correctness-sensitive)
| Optimization | Effort | Impact | Risk | Status | Reasoning |
|---|---|---|---|---|---|
| Incremental suffix min/max in `_detect_luminance` | M | Med | Med | ⏳ DEFERRED | The 66 ms window holds only ~2 records at 15 fps (~7 for a 10 ms GIF delay), so there is no real asymptotics win; "incremental" is mostly rolling buffers and less copying. It also requires moving from whole-grid vectorized ops to indexed ops, where fancy-indexing overhead can exceed the savings on dense frames. Risky for a modest payoff. |
| Short-circuit in `_detect_red` | M | Med | Med | ✅ DONE | Whole-detector red guard: early-out when no saturated-red tile exists anywhere in the window (verified semantics-preserving; the incremental red pool is exact, rebuilt on prune). See Phase 3. |
| Cache area evaluations | M | Med | Med | ⏳ DEFERRED | `AreaEvaluator.evaluate` reuses overlapping masks, but memoizing on mask identity/hash has an unclear hit-rate in practice. Benchmark before investing. |
| Avoid `pop(0)` on history list | S | Low | Low | ⏳ DEFERRED | Trivially low value; and the engine indexes history positionally (`history[0]`, `history[1]`, `history[index]`), while `deque` has no integer indexing, so the "simple" swap would need more churn than it saves. Defer. |

## Implementation plan

### Phase 1: Quick wins (low risk, good for GIFs)
1. **sRGB->linear LUT** in `color.py` - replace `np.where` + power with LUT indexing. Add `@lru_cache` or module-level array.
2. **Optimize `tile_frame` allocations** - try to avoid some PIL object creation; test numpy box downsample.
3. **Reduce copies in GIF compositing** - audit `_pillow_frames` for unnecessary `.copy()` calls.

Status: ✅ DONE (0.2.x). The LUT is module-level; tiling has a uint8 path that skips PIL for same-size grids and composites RGBA over black in numpy; the GIF decoder keeps canvas snapshots by reference because compositing never mutates its inputs.

### Phase 2: Medium effort (GIF-focused)
1. **Numpy box downsample** implementation - replace PIL resize path, keep fallback or flag.
2. **Fuse color transforms** in engine to cut passes.
3. **Optimize canvas compositing** - use numpy arrays where feasible.

Status: ✅ DONE (0.2.x).
1. `area.py` has an exact numpy BOX implementation (Pillow-compatible fixed-point coefficients, prefix-sum axis passes) but it is used as a fallback, not the normal path: benchmarking showed Pillow's C resize is roughly 5-8x faster for real downscales inside this pipeline. `tile_frame_uint8` exposes the uint8 tile averages without a float round-trip; `tile_frame` remains the public float wrapper.
2. `color.py` exposes `linear_rgb_features`, which computes luminance, redness, the saturated-red mask, and CIE UCS in one pass; `engine.py` uses it. The sRGB LUT now matches the float32 path exactly.
3. `decode.py` keeps an RGBA numpy canvas and vectorizes Pillow's `AlphaComposite.c` integer formula. Opaque and fully transparent sources take cheap paths; disposal semantics are unchanged.
Results matched the captured baseline for the benchmark set; GIF timings improved modestly. No detector semantics, warnings, assumptions, or the `tile_grid_max` default changed.

### Phase 3: Algorithmic (careful testing)
Status: 🟡 **PARTIAL** — 2 implemented, 4 deferred. Unlike phases 1-2 these change the shape of the per-frame computation, so the acceptance bar is bit-identical events, not just identical smoke-fixture output. Only pursued after phases 1-2 profiling confirmed the engine is *not* a material share of GIF runtime, so the payoff is modest and only the safe items were worth the risk.

Implemented in `engine.py`, gated behind a single instance flag `TransitionEngine._enable_short_circuit` (default `True`; kept on the instance, not an `AnalysisOptions` field, so an equivalence test can toggle it). Each item is independently revertible.

1. **Incremental suffix min/max in `_detect_luminance`** — ⏳ DEFERRED (risky, modest payoff; see reasoning in the engine/area table).
   - What it means: for every history record the engine needs the min and max luminance of that record *and every newer record still in the 66 ms window* (`suffix_min`/`suffix_max` in `engine.py`). Those arrays define the local-extremum test that identifies where a transition started. Today `add_frame` appends one record, prunes the window, then rebuilds the whole suffix structure from scratch with two fresh arrays per history entry.
   - The idea: keep the suffix state as a rolling structure tied to the sliding window and update it on append/prune instead of rescanning, avoiding per-frame allocation and Python loop overhead.
   - Caveat: the window is short, so the history is tiny (about 2 records at 15 fps, up to roughly 7 for a 10 ms GIF delay). There is no real asymptotics win; appending a frame can invalidate every earlier suffix value, so "incremental" mainly means rolling buffers and less copying, and the payoff is modest.
   - Must preserve: the coarse-step rule (`step_index` / `step_is_coarse`, which reports an unresolved single-frame step as `duration_ms=0`), and the pruning rule that keeps at least two records so the earliest can serve as `previous` for the next one. Suffix extrema for in-window indices only look at newer records, so the out-of-window reference record does not widen the extremum window.

2. **Engine short-circuiting** — 2 of 4 implemented.

Status: the two safe candidates are implemented; the risky/modest-payoff ones are deferred.
- **Whole-detector red guard.** ✅ DONE. `_detect_red` computes UCS distances for every history record before applying `(record.red | now.red)`. If neither the current frame nor any history record has a saturated-red tile, `valid` is all-false by construction, so an early return is exactly semantics-preserving. The running red pool is maintained incrementally in `add_frame` and rebuilt on a prune; it is always exact over the window. The engine takes this path for most ordinary content. The per-record red candidate check and window-range prefilter remain deferred.
- **Per-record red candidate check.** ⏳ DEFERRED — whether this beats whole-grid vectorization depends on mask sparsity; benchmark instead of assuming.
- **Window-range prefilter in `_detect_luminance`.** ⏳ DEFERRED (risky) — a tile whose window-wide range (`suffix_max[0] - suffix_min[0]`) is too small can be excluded, but the safe bound is model-dependent: under `wcag_relative` the SDR threshold is the bound, while under `cd_m2` the HDR Michelson branch can qualify a pair whose absolute difference is below `threshold * reference` (with `low >= 0.8 * reference` it needs at least `1.6 / 17` of relative luminance), so the prefilter must use the smaller of the SDR and HDR bounds. Getting it wrong silently drops real HDR flashes. Also requires moving from whole-grid ops to indexed ops, and fancy-indexing overhead can exceed the savings on dense frames.
- **Duplicate-frame skip.** ✅ DONE. If the new tile grid is elementwise identical to the previous record, all differences are zero and neither detector can fire. The record must still be appended (it changes future windows), but the per-frame detection pass can be skipped. Correctness note: the skip is safe only when the most recently detected frame changed **neither** luminance nor red direction state (tracked in `self._last_frame_changed_direction`, set from the luminance `choose_up|choose_down` union OR'd with the red `allowed` set). A duplicate following a direction change can itself complete a flash pair (a "down then immediately up"), so only the frames after a no-op detection are skippable; the flag is left untouched on a skip so an entire static run stays gated on the first frame that actually ran detection. The grid is small (192 x 192 x 3), and repeated GIF frames are common.
- **Area evaluation cache.** ⏳ DEFERRED — memoizing on mask identity/hash; overlapping masks are the norm, so the hit-rate is unclear. Benchmark before revisiting.
- **Must not do:** abort a file once the 7-transitions-per-second limit is exceeded. That shortens triggering media but changes reported measurements (`max_area`, `max_transition_duration_ms`, event counts, fast-flash merging) and the meaning of a full-file scan. The intent is skipping irrelevant work, not early verdicts.

## Considerations
- ✅ **Equivalence test (done).** `tests/test_engine_optimization.py` runs one history through the engine with `TransitionEngine._enable_short_circuit` toggled on and off and asserts identical events and measurements. Randomized histories are biased to the plan's risk cases: exactly-at-threshold luminance steps, the local-extremum tolerance boundary, red tie-breaking, and the coarse single-frame step. Smoke fixtures alone are not sufficient here. Real-content equivalence is covered by `tests/test_golden_media.py` (opt-in via `EPILEPSY_GOLDEN_EQUIP=1`), which toggles the same flag over the actual decode path (GIF loop repeat, loop-seam compositing, disposal, sampling) and asserts an identical measured surface.
- ⏳ **Re-profile before/after each remaining item (in progress).** The engine loops are vectorized across tiles already, so small-history assumptions may not hold at high frame rates; confirm the two implemented items actually net positive with a benchmark before declaring Phase 3 closed.
- Keep changes independently revertible, one idea per commit, so a benchmark regression can be attributed.

## Notes
- GIFs are the primary use case - prioritize decode/compositing and tiling over video-specific optimizations.
- 15 fps default sampling is correct for videos but irrelevant for GIFs; keeping it is fine.
- Tile grid default of 192 must remain (lowering breaks detection as shown).
- All optimizations must preserve warnings/assumptions and standards-explicit behavior.
