# About

## MEDHIRA

**Engineering Intelligence Across Everything.**

MEDHIRA builds tooling that gives developers and teams structural understanding of their own work — code, documents, recordings, the lot. We believe engineering intelligence belongs on your machine, not behind a vendor paywall.

Super-Brain is our flagship project. It exists because every AI coding assistant we tried shipped the same limitation: a fresh amnesia at the start of every session, billed by the token. We wanted something permanent, local, honest about what it knows, and fast enough to keep up with a fast-moving codebase.

---

## Why we built Super-Brain

Three beliefs drove the design:

1. **Your code should never leave your machine** unless you explicitly want it to. Most teams don't.
2. **Structure is more trustworthy than prose.** An LLM explaining a call graph is guessing. A tree-sitter AST walking the same call graph is observing.
3. **Persistence beats recomputation.** A graph built once is cheaper — and more correct — than an assistant reading the same files every conversation.

Super-Brain is our implementation of those three beliefs.

---

## Principles we don't compromise on

- **Local by default.** No account, no telemetry, no cloud dependency. An airplane-mode laptop runs Super-Brain end to end.
- **Deterministic ingestion.** The graph is built by parsers, not by language models. You can diff it and trust the diff.
- **Open by default.** Apache 2.0. No paid tier, no "enterprise edition", no telemetry ransom.
- **One command to integrate.** Fourteen supported IDEs, fourteen one-line install commands.
- **Accurate docs.** Every command example in these docs is verified against the shipping code. If we say it works, it works.

---

## Get in touch

- **Email** — [hello.medhira@gmail.com](mailto:hello.medhira@gmail.com)
- **GitHub** — [github.com/HELLOMEDHIRA](https://github.com/HELLOMEDHIRA)
- **Issues** — [github.com/HELLOMEDHIRA/agsuperbrain/issues](https://github.com/HELLOMEDHIRA/agsuperbrain/issues)
- **LinkedIn** — [linkedin.com/in/smuniharish](https://www.linkedin.com/in/smuniharish)

---

## Contributing

Pull requests welcome. For anything non-trivial, open an issue first so we can align on approach.

Ways to help even without writing code:

- File bugs with a small reproduction
- Tell us which IDE integration we should add next
- Share how Super-Brain fits into your workflow — we learn a lot from use cases we didn't anticipate

---

## License

Super-Brain is released under the **Apache License 2.0**. See [LICENSE](https://github.com/HELLOMEDHIRA/agsuperbrain/blob/main/LICENSE) for the full terms. In plain language: use it commercially, modify it, redistribute it, just keep the notice intact.

---

## Thanks

Super-Brain stands on the shoulders of excellent open-source work. A partial list:

- [tree-sitter](https://tree-sitter.github.io/) — 306-language AST parsing
- [KùzuDB](https://kuzudb.com/) — embedded graph database
- [Qdrant](https://qdrant.tech/) — vector search
- [sentence-transformers](https://www.sbert.net/) — embeddings
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — local transcription
- [MarkItDown](https://github.com/microsoft/markitdown) — document conversion
- [llama.cpp](https://github.com/ggerganov/llama.cpp) — local LLM inference
- [Typer](https://typer.tiangolo.com/) · [Rich](https://rich.readthedocs.io/) — the CLI experience

If you maintain one of these, thank you. Super-Brain wouldn't exist otherwise.

---

Made with care by [MEDHIRA](https://medhira.readthedocs.io/en/latest/).
