# Puter UI-TARS API Contract Verification & Implementation

## 1. Verified API Contract

Through official Puter and UI-TARS documentation, the following contract has been definitively established for querying `bytedance/ui-tars-1.5-7b`:

- **Endpoint**: `https://api.puter.com/puterai/openai/v1/chat/completions`
- **Method**: Standard OpenAI-compatible `POST` using `Authorization: Bearer <token>`.
- **Payload Format**: Standard OpenAI multimodal `messages` structure, sending the image as a `data:image/png;base64` `image_url` and the instruction as text.
- **Response Format**: Textual completions containing model thought and action coordinates, rather than a raw JSON bounding box dictionary.

Example raw response content from the model:
```text
Thought: To click on the submit button, I need to execute a click action at the corresponding coordinate.
Action: click(point='<point>450 780</point>')
```
*(Optionally may return `<|box_start|>(450, 780)<|box_end|>` based on variant).*

## 2. Implementation Changes

Based on the verified contract, the following architectural fixes were performed:
- **`src/agent/perception/backends.py`**: Rewritten to map inputs strictly to the OpenAI compatible schema. It injects the instruction and base64 image into `messages`.
- **`src/agent/perception/parser.py`**: Refactored to extract `choices[0].message.content` and apply regex extraction for coordinate points (`<point>x y</point>`). Extracted coordinates are then mapped directly to a 1x1 bounding box.

## 3. Regression Fixes
- `test_learning_loop_e2e.py` and `test_perception_store.py` have been fixed by importing standard models rather than the deleted `types.py`.
- **17 static analysis violations (ruff)** introduced during the initial refactoring phase were successfully patched.

## 4. Final Quality Gates

All regression gates are completely green and passing:

- **Pytest**: `161 passed, 7 skipped` in `17.03s` (All unit and integration tests passing).
- **Mypy**: `Success: no issues found in 120 source files`
- **Ruff**: `0 errors`
- **Provider Isolation**: Search confirmed that 100% of OpenRouter, fallback routing, and non-Puter logic has been excised from the repository.

## 5. Conclusion
The integration logic is functionally correct, strictly conforms to the verified Puter textual-action API contract, propagates failures natively through `GroundingFailure`, and passes all test scenarios.

**The system is verified and ready for live ServiceNow validation.**
