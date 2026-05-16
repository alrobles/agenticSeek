# KU HPC Slurm Operations

## Overview

KU HPC uses the Slurm workload manager. All cluster operations go through the agenticplug gateway and reumanlab bastion — never directly from the local laptop.

## Target Operations (Allowlisted)

### Phase 1 (Read-Only — PoC)

| Operation | Slurm Command | Gateway Path |
|-----------|--------------|--------------|
| `list_jobs` | `squeue -u <user> --json` | `GET /cluster/jobs/list` |
| `job_status` | `sacct -j <job_id> --json` | `GET /cluster/jobs/status?job_id=<id>` |

### Phase 2 (Write — Future)

| Operation | Slurm Command | Gateway Path |
|-----------|--------------|--------------|
| `submit_job` | `sbatch <script>` | `POST /cluster/jobs/submit` |
| `cancel_job` | `scancel <job_id>` | `POST /cluster/jobs/cancel` |
| `tail_job_log` | `tail -n <N> <log_path>` | `GET /cluster/jobs/log?job_id=<id>&lines=50` |

### Phase 3 (Advanced — Future)

| Operation | Description | Gateway Path |
|-----------|-------------|--------------|
| `sync_repo` | Git clone/pull to cluster work dir | `POST /cluster/repo/sync` |
| `read_allowed_artifact` | Read output files (allowlisted paths only) | `GET /cluster/artifacts/read` |
| `open_pr_for_result` | Create GitHub PR from cluster results | `POST /cluster/github/pr` |

## Slurm Command Reference

### squeue — List Jobs

```bash
# List all jobs for current user
squeue -u $USER

# JSON output (preferred for programmatic use)
squeue -u $USER --json

# Filter by state
squeue -u $USER -t RUNNING --json
squeue -u $USER -t PENDING --json
```

### sacct — Job Accounting

```bash
# Job status by ID
sacct -j <job_id> --format=JobID,JobName,State,ExitCode,Elapsed,NodeList --parsable2

# JSON output
sacct -j <job_id> --json

# Recent jobs for user
sacct -u $USER --starttime=now-7days --json
```

### sbatch — Submit Job

```bash
sbatch --job-name=myjob --output=logs/%j.out --error=logs/%j.err script.sh
```

### scancel — Cancel Job

```bash
scancel <job_id>
```

## JSON Response Shape (Expected from Gateway)

### list_jobs response

```json
{
  "status": "success",
  "operation": "list_jobs",
  "data": {
    "jobs": [
      {
        "job_id": "12345",
        "name": "train_model",
        "state": "RUNNING",
        "partition": "gpu",
        "nodes": "node01",
        "time_elapsed": "02:30:00",
        "time_limit": "24:00:00",
        "user": "reumanlab"
      }
    ]
  },
  "audit_id": "audit-abc123",
  "timestamp": "2026-05-15T12:00:00Z"
}
```

### job_status response

```json
{
  "status": "success",
  "operation": "job_status",
  "data": {
    "job_id": "12345",
    "name": "train_model",
    "state": "COMPLETED",
    "exit_code": "0:0",
    "elapsed": "01:45:23",
    "nodes": "node01",
    "work_dir": "/scratch/reumanlab/experiment_1"
  },
  "audit_id": "audit-def456",
  "timestamp": "2026-05-15T13:00:00Z"
}
```

## Error Handling

Gateway errors follow a consistent shape:

```json
{
  "status": "error",
  "operation": "job_status",
  "error": {
    "code": "JOB_NOT_FOUND",
    "message": "Job 99999 not found in Slurm accounting"
  },
  "audit_id": "audit-ghi789",
  "timestamp": "2026-05-15T14:00:00Z"
}
```

## Security Constraints

- All Slurm commands are executed on the KU HPC login node or reumanlab bastion, never on the local laptop.
- The agenticplug gateway validates operation names against its own allowlist before forwarding.
- Audit IDs are generated per request for traceability.
- File paths in file-read operations are restricted to allowlisted directories.
- Job submission requires pre-approved job scripts; no arbitrary sbatch.
