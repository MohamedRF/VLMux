# Safety

Model output is untrusted. The execution pipeline is:

```text
HTTP response → JSON extraction → VAP schema → coordinate mapping → bounds → policy → executor
```

Malformed output and out-of-image coordinates can receive only the configured bounded repair
attempts. Normal CLI output does not include provider response bodies or authorization values.

The local policy engine classifies paste as sensitive and window closing as destructive. Those
classes require human confirmation by default. TOML configuration can change confirmation and
deny sets using `safe`, `sensitive`, `external_side_effect`, and `destructive` risk names. A deny
decision cannot be overridden by the confirmation callback.

Dry-run captures the screen, calls the model, and validates one proposed action without creating a
desktop executor or executing input. `--offline` allows only localhost model URLs. This protects
against accidental remote screenshot upload, but it does not sandbox the configured local model.
