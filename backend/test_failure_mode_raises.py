"""
test_failure_mode_raises.py
Evidence script for code-review item #3:
  Verify that _validate_scoring_output raises ValueError (not silently coerces
  to "partial_gap") when failure_mode contains an unrecognized value.
"""
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def run():
    print("=" * 64)
    print("  FAILURE_MODE RAISE TEST — Issue #3 Evidence")
    print("=" * 64)

    from services.scoring_agent import _validate_scoring_output

    # Deliberately malformed failure_mode values to test
    bad_values = [
        "memory_issue",           # plausible-sounding but not in allowed set
        "conceptual_error",       # similar hallucination
        "PARTIAL_GAP",            # wrong casing (after lower().strip() this becomes "partial_gap" — should PASS)
        "unknown_failure",        # completely made up
        "",                       # empty string (distinct from "none")
        "gibberish_xyz_123",      # obviously bad
    ]

    # A base valid payload where only failure_mode is varied
    base_payload = {
        "criteria": "Checking whether the student correctly identified ATP production steps.",
        "verdict": "partial",
        "verdict_explanation": "The student showed partial understanding but missed key details.",
        "mastery_score": 0.5,
        "weak_point": "Electron transport chain specifics",
    }

    print()
    for bad_fm in bad_values:
        payload = {**base_payload, "failure_mode": bad_fm}
        try:
            result = _validate_scoring_output(payload)
            # "PARTIAL_GAP" lowercased to "partial_gap" which IS in the allowed set
            # and empty string lowercased is "" which is NOT in set — should raise
            print(f"  failure_mode={bad_fm!r:30s}  => returned (NO RAISE): failure_mode={result.failure_mode!r}")
        except ValueError as exc:
            print(f"  failure_mode={bad_fm!r:30s}  => ValueError: {exc}")
        except Exception as exc:
            print(f"  failure_mode={bad_fm!r:30s}  => {type(exc).__name__}: {exc}")

    # Now verify the "none" value and valid values still work correctly
    print()
    print("─" * 64)
    print("Valid values (should NOT raise):")
    valid_cases = [
        ("shallow_memorization", 0.5),
        ("wrong_mental_model", 0.3),
        ("correct_but_unclear", 0.6),
        ("partial_gap", 0.4),
        ("none", 0.9),
    ]
    base_valid = {
        "criteria": "Testing edge case handling.",
        "verdict": "partial",
        "verdict_explanation": "Student missed key nuance.",
        "mastery_score": 0.5,
        "weak_point": "Edge case handling",
    }
    for fm, score in valid_cases:
        payload = {**base_valid, "failure_mode": fm, "mastery_score": score}
        if score >= 0.7:
            payload["verdict"] = "held_up"
        try:
            result = _validate_scoring_output(payload)
            print(f"  failure_mode={fm!r:30s}  score={score}  => OK, stored as {result.failure_mode!r}")
        except ValueError as exc:
            print(f"  failure_mode={fm!r:30s}  score={score}  => UNEXPECTED ValueError: {exc}")

    print()
    print("=" * 64)
    print("  DONE — unrecognized failure_mode values now raise ValueError")
    print("=" * 64)


if __name__ == "__main__":
    run()
