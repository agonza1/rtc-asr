# Performance Benchmarks

> Validation status: benchmark figures for this project are currently unvalidated. Do not treat any previously published latency, throughput, memory, or accuracy numbers as authoritative until the real ASR implementation and benchmark harness are complete.

## Current Status

The repository is in a transition period:

- The production transcription path is being wired to a real ASR backend.
- The benchmark harness for reproducible measurement is not finished.
- Historical benchmark tables that appeared in earlier drafts of this repository should be treated as placeholders, not measured results.

## What Will Be Published After Validation

The benchmark document will be repopulated once the following are in place:

- A reproducible benchmark harness checked into the repository
- A documented test environment and model/backend configuration
- Measured latency distributions for representative REST and streaming workloads
- Throughput and resource-usage measurements under defined concurrency levels
- Accuracy evaluation against a documented fixture set or external dataset

## Planned Benchmark Methodology

### Environment Capture

Record the following for each run:

- Host CPU/GPU and memory
- OS and Python versions
- Model/backend version and configuration
- Container or bare-metal execution mode

### Workloads

Measure at minimum:

- File transcription via `POST /api/transcribe`
- Streaming transcription once `/ws/stream` maintains connection state and emits partial/final results
- Small, medium, and long audio fixtures
- Single-request and concurrent-request scenarios

### Metrics

Collect and publish:

- End-to-end latency percentiles
- Throughput under fixed concurrency
- Memory and CPU/GPU usage
- Word error rate or another clearly defined accuracy metric

## Until Then

- Use this project documentation for API shape and integration guidance, not performance guarantees.
- Treat latency-related configuration values as operational knobs, not proof of measured performance.
- Avoid repeating benchmark claims in downstream docs, demos, or release notes until measured results are available.
