# CI expectation

CI must at minimum exercise the frozen classifier behavior and importability. Production database acceptance is a separate read-only recovery operation and must not be simulated by declaring CI success equivalent to Step 14 completion.
