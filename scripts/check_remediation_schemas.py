"""Validate remediation JSON formats only; never executes requests or approves work."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "docs" / "ai-native-remediation" / "schemas"
NAMES = ("review-request", "review-result", "harness-status",
         "harness-checkpoint", "recovery-event")


def validator(name):
    from jsonschema import Draft202012Validator, FormatChecker
    if name not in NAMES:
        raise ValueError("UNKNOWN_SCHEMA")
    schema = json.loads((SCHEMAS / (name + ".schema.json")).read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def valid(name, payload):
    return validator(name).is_valid(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", choices=NAMES)
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    if bool(args.schema) != bool(args.input):
        parser.error("--schema and --input must be supplied together")
    try:
        if args.input:
            if args.input.is_symlink() or args.input.stat().st_size > 1_000_000:
                print("INVALID_INPUT_FILE")
                return 1
            payload = json.loads(args.input.read_text())
            if not valid(args.schema, payload):
                # Do not print validation error payloads: caller data is untrusted.
                print("SCHEMA_VALIDATION_FAILED")
                return 1
            print("SCHEMA_VALID_FORMAT_ONLY_NOT_APPROVAL")
        else:
            for name in NAMES:
                validator(name)
            print("SCHEMAS_VALID: 5 (format only)")
        return 0
    except ImportError:
        print("NOT_VERIFIED: jsonschema>=4 required", file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print("INVALID_INPUT_OR_SCHEMA", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
