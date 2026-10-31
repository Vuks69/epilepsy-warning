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

### Phase 3: Algorithmic (careful testing)
1. **Incremental suffix arrays** in engine
2. **Engine short-circuiting**

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
