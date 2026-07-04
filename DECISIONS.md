# Decision Journal

A running log of key decisions on the Fantasy Football Assistant project — what was decided, why, and what alternatives were considered. Kept for two reasons: to keep the project coherent as it grows, and to give portfolio reviewers a window into the thinking behind the build.

Newest entries at the top.

---

## 2026-07-04 — Project kickoff and repo setup

**Context:** Starting the Fantasy Football Assistant project. Goal is to manage teams across multiple leagues and platforms, with the build documented for a job-seeking portfolio alongside a public GitHub repo (https://github.com/keithtruong/fantasy-football-assistant).

**Decisions:**

- **Documentation-first start.** Before any solutioning on scope or architecture, set up a README and a decision journal so every subsequent choice gets recorded as it happens rather than reconstructed later.
- **Decision log format:** a single `DECISIONS.md` file (not a per-entry folder), written in portfolio-readable style — plain-English context and rationale, not just terse commit-style notes — since this doubles as a work sample for recruiters.
- **Git setup:** local repo initialized with `origin` pointed at the existing GitHub repo; push deferred until credentials/auth are confirmed.

**Note on environment:** git operations against the connected project folder failed in this session — the folder is mounted through a network/FUSE layer that doesn't support git's file-locking behavior (`.git/config` came back corrupted). Repo history was built in a local sandbox path instead, with the plain files copied into the project folder. Running `git init` directly from a native terminal on the local machine (not through this mount) is expected to work normally — see the commands below.

**To connect this folder to GitHub, run from a terminal in this folder:**

```
git init
git add .
git commit -m "Initial commit: README and decision journal"
git branch -M main
git remote add origin https://github.com/keithtruong/fantasy-football-assistant.git
git push -u origin main
```

**Next up:** high-level discussion of project scope (leagues, platforms, core use cases) before any architecture or tooling decisions are made.
