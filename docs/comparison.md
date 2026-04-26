# Why Super-Brain

AI coding assistants are brilliant at generating code and explaining one function at a time. They struggle the moment a task spans more than a few files. Super-Brain fixes that gap.

This page lists **12 concrete pain points** you hit every week with Claude Code, Codex, Cursor, Copilot, or any other assistant — and what Super-Brain does about each one.

---

## At a glance

| Pain point | Claude Code / Codex / Cursor / Copilot alone | With Super-Brain |
|---|---|---|
| 1. Session amnesia | Starts from zero every session | Graph persists on disk |
| 2. Re-reading the same files | File reads every turn | One ingest, then queries |
| 3. Grep-based exploration | Regex match on text | Semantic vector + graph |
| 4. No real call graph | Inferred per-question | Deterministic AST-derived |
| 5. Path reasoning | Chains of file reads | `path_between` in one hop |
| 6. "Who uses this?" | Best-effort text search | Transitive closure |
| 7. Cross-repo blindness | One project at a time | Unlimited repos, one graph |
| 8. Docs and audio | Ignored or pasted as blobs | First-class modalities |
| 9. Hallucinated dependencies | Possible under load | Zero — AST is ground truth |
| 10. Token cost for exploration | Scales with codebase size | Flat, query-shaped |
| 11. Privacy / compliance | Code uploads to vendor cloud | Nothing leaves your machine |
| 12. Language coverage | Top 15-20 | 306 via tree-sitter |

---

## The 12 problems, in detail

### 1. Session amnesia

**The problem.** Close Claude Code, reopen it — your assistant forgets everything it learned about your codebase. Same with Codex, same with Cursor, same with Copilot. Every session rediscovers the same architecture.

**Super-Brain's fix.** The graph lives in a file on your disk (KùzuDB). It's built once, updated incrementally by the file watcher, and available to every future session instantly. Restart your IDE ten times a day — structural knowledge survives all of it.

---

### 2. Re-reading the same files

**The problem.** Ask Claude Code *"how does the auth middleware work?"* on Monday and again on Friday. Both times it opens the same 6 files, reads them end to end, and pays for the tokens. Multiply by every team member, every day.

**Super-Brain's fix.** One ingest builds a structured index. After that, questions resolve against the graph instead of a file-read loop. Your assistant pulls just the functions it actually needs, with their docstrings and call edges pre-computed.

---

### 3. Grep-based exploration

**The problem.** Ask for *"the place that validates JWT tokens"* and a text-matching assistant greps for `JWT` or `validate`. It misses the function that's actually named `ensure_bearer_legitimacy`. Semantic queries degrade to keyword search.

**Super-Brain's fix.** Every function, method, and chunk of documentation is embedded as a vector. A query for *"validate JWT"* finds `ensure_bearer_legitimacy` because they're semantically close, regardless of naming. Graph expansion then pulls in the adjacent functions that actually matter.

---

### 4. No real call graph

**The problem.** When you ask *"what happens if `processPayment` throws?"*, a plain assistant has to build a fragile mental model from file reads. It sometimes invents relationships that aren't in the code — a well-known failure mode at the edge of its context.

**Super-Brain's fix.** Call edges come from the AST, via tree-sitter. A function either calls another or it doesn't. No inference, no hallucination, no "probably". Ask for callers of `processPayment` and you get exactly the functions the parser found — nothing more, nothing less.

---

### 5. Path reasoning

**The problem.** *"How does data flow from the HTTP handler into the database?"* This is a multi-hop question. Text-based assistants chain several file reads and can easily lose the thread halfway through.

**Super-Brain's fix.** `path_between(src, dst)` returns the exact call path as a sequence of node IDs, hop by hop. Your assistant can read just the functions on the path — usually three or four — instead of wandering through a dozen files.

---

### 6. "Who uses this?" — transitive closure

**The problem.** You want to know every function affected if you change `serialize_order`. A plain assistant does `grep serialize_order` and hopes callers aren't wrapped in dynamic dispatch, reflection, or an alias.

**Super-Brain's fix.** `closure(node_id, relation="CALLS", max_hops=10)` walks the reverse-call graph and returns the full impact surface. You get every direct caller, every indirect caller, up to any depth. No surprises at review time.

---

### 7. Cross-repo blindness

**The problem.** Your system is a monorepo-plus-a-few-services. Each repo is a different Cursor window, a different Claude Code session. Knowledge doesn't cross. When a shared type changes, nobody sees the impact in the other repo until CI fails.

**Super-Brain's fix.** Run `agsuperbrain ingest` against as many repositories as you want. They all land in one graph. Ask questions that cross repo boundaries. The graph knows that service A's `OrderPayload` is the same one service B is deserializing.

---

### 8. Documents and audio

**The problem.** The decision that says "we're using Postgres, not MySQL" lives in a design doc from 2024. The performance trade-off was debated on a recorded call. An AI coding assistant ignores both — they're not code.

**Super-Brain's fix.** `ingest-doc` handles PDF, DOCX, PPTX, MD; `ingest-audio` handles MP3/WAV/MP4 and even YouTube URLs via local Whisper. Both feed the same graph and link to the code they describe via keyword overlap. Ask *"what meeting decided we'd use Postgres?"* and get the transcript segment plus the PRs that followed.

---

### 9. Hallucinated dependencies

**The problem.** Under heavy context pressure, LLMs sometimes emit plausible-looking call relationships that don't exist in the code. You trust the explanation and ship a refactor that breaks something the model invented.

**Super-Brain's fix.** Every structural fact in the graph came from tree-sitter walking an AST. If Super-Brain says function A calls function B, the parser observed it at a specific line in a specific file. "Made up" isn't a failure mode the architecture permits.

---

### 10. Token cost for exploration

**The problem.** Large context windows are not free. Exploring a 100k-LOC codebase by letting your assistant read files is linear in codebase size — $X per question, growing with every file added.

**Super-Brain's fix.** The cost of a Super-Brain query is flat. It's one vector search plus one or two graph expansions. The answer ships just the relevant function bodies — usually a few hundred tokens total — no matter whether the repo is 1k lines or 1M.

---

### 11. Privacy / compliance

**The problem.** Anthropic, OpenAI, Microsoft, and Google all receive your source code when you use their coding assistants. For many teams — banks, hospitals, government contractors, any regulated domain — that's a non-starter.

**Super-Brain's fix.** Everything runs on your machine:

- Graph: local KùzuDB file
- Vectors: local Qdrant directory
- Embeddings: local sentence-transformers
- Optional LLM: local llama.cpp with Llama-3.2-1B
- Audio transcription: local faster-whisper

You can disconnect your network cable and Super-Brain keeps working. Your assistant of choice still sees only the small evidence bundles it needs — not the whole codebase.

---

### 12. Language coverage

**The problem.** Top-tier assistants do well on Python, TypeScript, Go. They're noticeably weaker on Kotlin, Dart, Elixir, Nim, Zig, and everything rarer. Mixed-language codebases (think mobile app + C++ core + Python tools) get inconsistent treatment.

**Super-Brain's fix.** Tree-sitter supports **306 programming languages** via `tree-sitter-language-pack`. Super-Brain extracts functions, methods, and call edges from all of them. Tier 1 languages (Python, JS/TS, Go, Rust, Java, C, C++, C#, Ruby, PHP, Kotlin, Swift, Scala) get full extraction including method resolution. The rest get AST-level parsing and symbol extraction — still far beyond text matching.

---

## How Super-Brain changes the workflow

**Without Super-Brain:**

1. Open IDE
2. Ask a question
3. Wait while assistant reads 8 files
4. Receive answer
5. Ask follow-up
6. Wait while assistant re-reads most of the same 8 files
7. Repeat

**With Super-Brain:**

1. Open IDE
2. Ask a question
3. Assistant queries graph, gets 3 exact functions, answers
4. Follow-up question — same graph, different path, instant

That's the shape of the change. It compounds.

---

## When you might not need Super-Brain

Be honest — it's not for every codebase:

- Your project is 500 lines total. The context window already fits.
- You're using Claude Code / Cursor purely for single-file edits, not structural questions.
- You don't care about token cost and compliance isn't a concern.

For everything larger, longer-lived, or more sensitive, Super-Brain pays for itself on the first multi-file question.

---

## Next steps

- [Install](install.md) — one command
- [Quick Start](quickstart.md) — five-minute walkthrough
- [IDE Integration](mcp.md) — wire it into your assistant of choice
