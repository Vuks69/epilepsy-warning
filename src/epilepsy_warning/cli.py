#!/usr/bin/env python3
import sys
from .analyzer import FlashDetector


def main():
    if len(sys.argv) < 2:
        print("Usage: epilepsy-scan [file ...]", file=sys.stderr)
        sys.exit(1)

    detector = FlashDetector()
    results = {}

    for filepath in sys.argv[1:]:
        try:
            result = detector.analyze(filepath)
            results[filepath] = result
            # Print human readable output
            if result.get("is_triggering"):
                print(f"⚠️  {filepath}: TRIGGERING - {result.get('reason')}")
            else:
                print(f"✓  {filepath}: Safe - {result.get('reason')}")
        except Exception as e:
            results[filepath] = {"is_triggering": False, "error": str(e)}
            print(f"✗  {filepath}: Error - {e}", file=sys.stderr)

    # Exit code 1 if any triggering content found
    if any(r.get("is_triggering") for r in results.values()):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
