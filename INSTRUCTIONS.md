Copy `template.py` as your initial template for the project. It demonstrates how CLI arguments should be handled.

# Coding Instructions

- In case of non-standard linting error, consult the user.
- Prefer a single-file implementation when the program is small enough to stay readable.
- Keep external dependencies minimal. If one dependency is allowed, isolate it at the CLI boundary.
- Use `@dataclass(frozen=True, kw_only=True)` as the main data abstraction.
- Use `argparse` for CLI argument parsing.
- Put CLI parsing in an `Args.from_args(cls, argv: list[str] | None = None) -> Self` classmethod.
- Keep CLI defaults in `argparse` declarations, not duplicated on the `Args` dataclass fields.
- Entrypoints should call `raise SystemExit(Args.from_args().run())`.
- Keep `# /// script` dependency metadata only when it lists actual dependencies. The empty block remains in `template.py` only as a placeholder for scripts that later need dependencies.
- Put behavior on the data that owns it. Use methods or class methods for stateful logic, and namespace-style classes with static methods for cohesive stateless helpers.
- Keep constants as `ClassVar`s on the class that owns the behavior.
- Separate data processing from printing/rendering.
- Use precise `Literal[...]` aliases for string-mode values and kind dispatch. Avoid `Enum` when simple literals are enough.
- Prefer exhaustive `match` statements over kind `if`/`elif` chains. Include `case _:` with `assert_never(...)`.
- A walrus-bound subject is acceptable when it helps type checkers understand `assert_never`.
- Do not over-abstract. Remove dataclasses or wrappers that only add ceremony.
- Do not overuse `try`/`except`. Let normal exceptions propagate unless handling them adds real recovery or materially better behavior.
- Use `list[...]` for variable-size collections and `tuple[...]` for fixed-size return pairs.
- Use numeric separators for large literals, for example `40_000`.
- Keep CLI argument classes thin: parse inputs, call core logic, print output, return exit codes.
- `argparse` may not preserve rich annotations such as `Literal[...]`; keep those fields runtime-compatible and cast at the boundary.
- Use path types deliberately: filesystem handles should be `Path`, while display names, labels, and external metadata should stay strings.
- Keep status documents current. Remove completed refactor notes instead of preserving stale warnings.
- Record the current verification command and the last meaningful validation state in handoff notes.
- Add doctests near small units of logic, and fixture tests for whole-program behavior.
- When fixture tests are small, prefer inline doctest docstrings over separate fixture files.
- Put doctest helpers in a small test namespace; keep test-only imports local.
- Test colored output explicitly when rendering uses ANSI.
- Keep fixtures small and organized by case.
- Use a simple Makefile: `all` should run formatting/fixes, lint/type checks, and tests. Run `make` regularly.
  - See the existing Makefile
- Maintain a short handoff/status document for ongoing refactors and unfinished decisions.
