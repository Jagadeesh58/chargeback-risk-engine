# Security Notes

- Never commit Razorpay credentials or API keys.
- The default Razorpay adapter is mock/draft-only and does not make network calls.
- Treat incoming dispute identifiers and evidence values as untrusted input.
- Keep deterministic policy outside the authority of model code.
- Reject malformed amounts and impossible values at the API boundary.
- Preserve idempotency for duplicate dispute/webhook events.
- Audit model, feature and policy versions for every decision.
