# Tech Stack Selection

The project is now a library, so the stack decisions are about **packaging, distribution, and
cross-language parity**, not bot hosting.

Requirements:
- Callable from Python and Go projects
- No LLM; fast enough for interactive use
- No cgo, no complicated native build chain for consumers
- Reproducible results across languages for the same media
- Minimal, well-maintained dependencies

## Language strategy

### Option A: Native implementations in both languages (recommended)
- Python package as the reference implementation
- Go module as a native port
- A shared, versioned **conformance suite** (fixtures + expected results) keeps them aligned

Pros:
- Idiomatic API in each ecosystem
- No cgo/FFI/subprocess bridge to distribute
- Each language can optimize decoding for its platform
- Python ships fastest; Go can follow once the algorithm stabilizes

Cons:
- Two codebases to maintain; drift is possible without strong conformance tests

Mitigation: the WCAG rules are small and deterministic. Treat the Python implementation as the
specification, keep the result schema identical, and run the same fixtures in both CI pipelines.

### Option B: One core plus bindings
Implement the core once (Go, Rust, or C) and expose Python bindings.

Pros:
- One algorithm implementation
- Consistent behavior by construction

Cons:
- cgo/FFI or a compiled extension complicates wheels and cross-platform distribution
- Debugging and contributions are harder
- Overkill for a CPU-light, rule-based analyzer

### Option C: CLI/subprocess bridge
Ship one binary/CLI and have both languages call it.

Pros:
- Trivial cross-language reuse

Cons:
- Process and temp-file overhead per scan
- Awkward error handling and cancellation
- Poor fit for high-throughput servers or in-memory bytes

**Recommendation: Option A.** Build the Python library first (the existing prototype already
proves the concept), stabilize the algorithm and result schema, then port to Go and validate
against the shared fixtures. Revisit Option B only if parity maintenance becomes painful.

## Python stack

- **Runtime**: Python >= 3.9 (keep in sync with `pyproject.toml`; consider 3.10+ once 3.9 is
  dropped upstream)
- **Build**: `hatchling`, `src/` layout, `py.typed` marker
- **Core deps**:
  - `numpy` - vectorized luminance/area math
  - `Pillow` - GIF/frame decoding and downsampling
  - `imageio` + `imageio-ffmpeg` - video frame iteration without a system ffmpeg requirement
- **Removed deps**: `discord.py`, `PyNaCl`, `aiohttp`, `python-dotenv` (no bot/network in core)
- **Optional extras**:
  - `[video]` for video decoding if we decide to keep it out of the base install
  - `[dev]` for pytest, ruff, mypy
- **Packaging**: publish to PyPI as `epilepsy-warning`; import package `epilepsy_warning`
- **Typing**: full annotations, PEP 561 marker, public API re-exported from `__init__.py`
- **CLI**: `epilepsy-scan` entry point, a thin wrapper over the library (useful for CI and manual
  checks; not the primary interface)

`imageio-ffmpeg` bundles an ffmpeg binary, which simplifies installation but should be treated
as an optional, replaceable decoder. The API must also accept caller-supplied frames so users
can avoid a bundled decoder entirely.

## Go stack

- **Module**: `github.com/<owner>/epilepsy-warning` (final path TBD when published)
- **Core deps**: standard library only for the analysis math and GIF decoding (`image/gif`)
- **Video decoding**: `os/exec` ffmpeg with argv arrays, streaming raw frames over stdout.
  No `shell=True` equivalent, no cgo.
- **Optional pure-Go decoding**: `golang.org/x/image` for additional still/animated formats where
  practical; video remains ffmpeg-backed
- **Packaging**: a normal Go module; consumers run `go get`
- **API**: context-aware (`AnalyzeFile(ctx, path, opts)`), no global state, options by value
- **Testing**: `go test`, table tests, same fixture corpus as Python

If requiring a system ffmpeg is unacceptable for a Go consumer, they can decode frames
themselves and call `epilepsy.AnalyzeFrames(...)`; the decoder boundary is part of the public API.

## Cross-language contract

- **Result schema**: a versioned, JSON-serializable struct/document. Field names and semantics
  must match across Python and Go.
- **Conformance fixtures**: small checked-in media files with expected classifications and
  tolerances for floating-point measurements.
- **Thresholds**: defined once in a shared document, duplicated as constants, and asserted by
  tests in both languages.
- **Semantic versioning**: schema or threshold changes that alter classifications are breaking
  changes (major version).

## Alternatives considered

- **OpenCV in the core**: powerful, but a large dependency for consumers and unnecessary for
  luminance math. Keep it as a dev/benchmark tool only.
- **moviepy/pyav**: heavier than needed and can pull in system codecs; `imageio` + ffmpeg covers
  the use case.
- **ML classifier**: rejected; training data is limited, inference is slower and opaque, and the
  WCAG rules already encode the relevant physics.

## Recommendation summary

Python reference library first, native Go port second, shared conformance fixtures and result
schema. Keep the core dependency-light, decoder-agnostic at the API boundary, and free of any
Discord/network code.
