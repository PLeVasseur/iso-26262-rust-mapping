<!-- fmt: align=center size=24 bold=true -->
ISO 26262-6:2018 to Rust 1.93.1

<!-- fmt: align=center size=16 bold=true -->
Complete Language and Standard Library Mapping

<!-- fmt: align=center size=12 -->
Reference for Safety-Critical Rust Coding Standards (QM to ASIL D)

<!-- fmt: align=center size=12 italic=true -->
Revision 2 — February 2026

<!-- fmt: align=center size=11 -->
Working reference for Safety-Critical Rust Consortium — Coding Guidelines Subcommittee

<!-- fmt: align=center size=10 -->
Baseline: Rust stable 1.93.1 (2026-02-12), Edition 2024 (no nightly features)

{{PAGE_BREAK}}

# Table of Contents

<!-- fmt: size=10 italic=true -->
Note: This document uses Word heading styles. To generate an automatic table of contents, insert a TOC field in Word and update.

<!-- fmt: style="List Paragraph" -->
1. Introduction and Scope

<!-- fmt: style="List Paragraph" -->
2. Review Notes and Critiques of Draft v1

<!-- fmt: style="List Paragraph" -->
3. ISO 26262-6:2018 Clause 5 — General Topics & Table 1 (Topics for Modelling/Coding Guidelines)

<!-- fmt: style="List Paragraph" -->
4. ISO 26262-6:2018 Clause 7 — Software Architectural Design (Tables 2–4)

<!-- fmt: style="List Paragraph" -->
5. ISO 26262-6:2018 Clause 8 — Software Unit Design & Implementation (Tables 5–6)

<!-- fmt: style="List Paragraph" -->
6. ISO 26262-6:2018 Clause 9 — Software Unit Verification (Tables 7–9)

<!-- fmt: style="List Paragraph" -->
7. ISO 26262-6:2018 Clause 10 — Software Integration & Verification (Tables 10–12)

<!-- fmt: style="List Paragraph" -->
8. ISO 26262-6:2018 Clause 11 — Testing of Embedded Software (Tables 13–15)

<!-- fmt: style="List Paragraph" -->
9. Configurable Software (Annex C) and Rust Configuration Practices

<!-- fmt: style="List Paragraph" -->
10. Rust Language Inventory — Complete Construct Classification (QM to ASIL D)

<!-- fmt: style="List Paragraph" -->
11. Standard Library Inventory — core/alloc/std Modules and Macros (QM to ASIL D)

<!-- fmt: style="List Paragraph" -->
12. Tooling, Qualification, and Evidence Strategy (ISO 26262-8)

<!-- fmt: style="List Paragraph" -->
13. ASIL Profile Summary Matrices

<!-- fmt: style="List Paragraph" -->
14. References

{{PAGE_BREAK}}

# 1. Introduction and Scope

This document maps ISO 26262:2018 (Road vehicles — Functional safety) software development expectations onto the Rust programming language and its standard library. It is intended to be used as an input to a project- or consortium-specific coding standard, and to support a defensible safety case (QM through ASIL D) for Rust-based automotive software.

## 1.1 Normative baselines and versioning

All technical guidance in this revision is anchored to the following baselines:
• ISO 26262-6:2018 clauses and tables (software development at the software level).
• Rust stable 1.93.1 standard library documentation (std/core/alloc) and Rust Reference keywords.
• Ferrocene Language Specification (FLS) as the qualification-oriented normative description of Rust language behavior, where applicable.

Because Rust evolves, this mapping is explicitly versioned. Any change to the Rust toolchain version, the Edition, or the set of approved dependencies requires re-assessing the impacted rows in the inventories in Sections 10–11 and updating the safety argument.

## 1.2 QM and ASIL applicability

ISO 26262 defines four Automotive Safety Integrity Levels (ASIL A–D) and a non-safety classification QM (Quality Management). QM items do not impose ISO 26262 safety requirements, but they still benefit from the same disciplined engineering practices. This document therefore provides a graded profile from QM (least restrictive) to ASIL D (most restrictive).

## 1.3 Interpretation of ISO 26262 table symbols

ISO 26262 tables classify methods and principles using symbols:
• “++” = highly recommended
• “+” = recommended
• “o” = neither recommended nor discouraged
and some clauses apply to ASIL values shown in parentheses as recommendations rather than requirements. This mapping preserves the intent by translating it into enforceable rules and evidence expectations.

## 1.4 Classification codes used in this mapping

Every Rust language construct, standard library module, or API surface is classified per safety level using the following codes:
• P  — Permitted (allowed without additional justification beyond normal review/testing)
• HR — Highly recommended (preferred default)
• M  — Mandatory (required when applicable)
• R  — Restricted (allowed only under stated constraints and documented rationale)
• Q  — Qualified-only / Trusted component (allowed only inside pre-approved, independently reviewed ‘TCB’ modules such as HAL/FFI/allocator)
• X  — Prohibited (not allowed in certified code)
• U  — Unavailable/unstable/experimental (not allowed in certified builds; requires nightly or non-qualified behavior)


## 1.5 Completeness rule and default-deny policy

Completeness is enforced by a default-deny rule: any Rust feature, attribute, macro, or standard library API not explicitly classified in Sections 10–11 is treated as X (Prohibited) for ASIL code, until reviewed and added. QM may optionally operate with default-allow, but doing so weakens re-use across ASIL levels; therefore, this document recommends using the same default-deny mechanism for all safety levels.

To keep the inventories complete as Rust evolves, projects should generate an automated API inventory (e.g., from rustdoc JSON) during CI and compare it against the approved allowlist. Any delta (new or removed items) must trigger a review and a documented mapping update.

## 1.6 ISO 26262-6:2018 clause and table cross-reference

This section provides an explicit mapping between the structure of this Rust language/library mapping and the corresponding ISO 26262-6:2018 clauses, tables, and annexes referenced throughout.

{{TABLE: table-01}}

# 2. Review Notes and Critiques of Draft v1

This revision started from a prior internal draft and applies several corrective and completeness-driven improvements. The critiques below are intended to be constructive review feedback and to explain why the document was restructured.

<!-- fmt: style="List Paragraph" -->
ISO 26262 table alignment: multiple tables were mis-numbered or mapped to the wrong content. For example, ISO 26262-6 Table 1 concerns topics for modelling/coding guidelines; architectural design principles are in Table 3, and unit design principles are in Table 6. Structural coverage metrics for unit testing are in Table 9; function/call coverage at the architectural level is Table 12.

<!-- fmt: style="List Paragraph" -->
Missing ISO topics: Table 1 includes an explicit concurrency topic (1i) which must be addressed by coding guidelines; earlier drafts focused on concurrency later but did not trace it back to Table 1.

<!-- fmt: style="List Paragraph" -->
Incomplete inventory: the standard library mapping covered only a subset of core/std modules and did not enumerate the full module/macro surface of Rust 1.93.1 (including experimental and deprecation-planned areas). A complete mapping must start from a complete inventory.

<!-- fmt: style="List Paragraph" -->
Insufficient QM coverage: earlier drafts began at ASIL A; this revision adds QM as an explicit profile and clarifies which restrictions are safety-motivated vs general quality-driven.

<!-- fmt: style="List Paragraph" -->
Ambiguity around panics and unwinding: earlier drafts discussed unwrap/expect but did not specify a complete panic policy (panic=abort vs unwind), FFI boundaries, or how panic-related APIs in std/core are treated per ASIL.

<!-- fmt: style="List Paragraph" -->
Unclear governance: a complete mapping must include an update mechanism (default-deny + automated inventory diff) so that new Rust releases or new dependencies cannot silently bypass the coding standard.

All subsequent sections incorporate these corrections and extend the mapping to a complete module/macro inventory for core/alloc/std as of Rust 1.93.1.

# 3. ISO 26262-6:2018 Clause 5 — General Topics & Table 1

ISO 26262-6 Clause 5 establishes expectations for the software development process and environment, including the selection of modelling/design/programming languages and the use of guidelines. Table 1 lists the topics that coding/modelling guidelines should cover. In Rust, many of these topics are partially satisfied by the language design (ownership, typing, safe/unsafe boundary), but they still require explicit project rules, tool configuration, and evidence.

## 3.1 ISO 26262-6:2018 Table 1 — Topics to be covered by modelling and coding guidelines

{{TABLE: table-02}}

{{BLANK}}

# 4. ISO 26262-6:2018 Clause 7 — Software Architectural Design (Tables 2–4)

Clause 7 focuses on constructing and verifying a software architecture that satisfies software safety requirements and supports implementation and verification. The architecture must capture static aspects (component structure, interfaces, data types) and dynamic aspects (control flow, concurrency, timing).

## 4.1 ISO 26262-6:2018 Table 2 — Notations for software architectural design

Rust does not prescribe a single architectural notation, but it provides strong support for architecture documentation through explicit module boundaries, visibility control, and auto-generated API documentation (rustdoc). For ASIL C/D, semi-formal representations (state machines, sequence diagrams, timing models) are typically needed alongside rustdoc.

{{TABLE: table-03}}

{{BLANK}}

## 4.2 ISO 26262-6:2018 Table 3 — Architectural design principles mapped to Rust

Table 3 architectural principles map naturally to Rust’s crate/module system and to explicit interface boundaries. The key safety contribution is to keep components small, cohesive, and isolated, and to manage shared resources and timing determinism explicitly.

{{TABLE: table-04}}

{{BLANK}}

## 4.3 ISO 26262-6:2018 Table 4 — Verification methods for the software architectural design

Table 4 lists verification methods (walk-through, inspection, simulation, prototype generation, formal verification, control/data flow analysis, scheduling analysis). In Rust projects, these map to architecture reviews, static analysis, model-based simulations (where applicable), and timing/resource analysis.

{{TABLE: table-05}}

{{BLANK}}

# 5. ISO 26262-6:2018 Clause 8 — Software Unit Design & Implementation (Tables 5–6)

Clause 8 focuses on unit-level design and implementation rules that prevent systematic faults and produce verifiable, readable source code. Rust eliminates some C/C++ failure modes by construction, but Clause 8 still requires explicit coding rules, especially for allocation, unsafe code, macros, and error handling.

## 5.1 ISO 26262-6:2018 Table 5 — Notations for software unit design

Unit-level design descriptions should be detailed enough to support implementation and verification. In Rust, this typically means:
• module-level docs describing responsibilities and invariants,
• state machine definitions (enums + transitions),
• interface contracts (preconditions/postconditions), and
• data structure invariants (including unsafe invariants when applicable).

## 5.2 ISO 26262-6:2018 Table 6 — Design principles for software unit design and implementation

{{TABLE: table-06}}

{{BLANK}}

# 6. ISO 26262-6:2018 Clause 9 — Software Unit Verification (Tables 7–9)

Clause 9 requires evidence that the unit design and implementation satisfy allocated requirements, implement safety measures, and contain neither unintended functionality nor unsafe properties. Rust contributes via strong static guarantees (initialization, borrow checking, data-race freedom in safe code), but verification still requires reviews, static analysis, testing, and coverage evidence.

## 6.1 ISO 26262-6:2018 Table 7 — Methods for software unit verification mapped to Rust

{{TABLE: table-07}}

{{BLANK}}

## 6.2 ISO 26262-6:2018 Table 8 — Test case derivation methods for unit testing

Rust unit tests should be derived systematically, not ad hoc. Table 8’s methods map well to typical Rust testing practices.

{{TABLE: table-08}}

{{BLANK}}

## 6.3 ISO 26262-6:2018 Table 9 — Structural coverage metrics at the software unit level

Table 9 requires measurement of unit-level structural coverage. For Rust, coverage tools must account for monomorphization, inlining, and compiler-generated code. For ASIL D, MC/DC is typically required and may need specialized tooling and test design.

{{TABLE: table-09}}

{{BLANK}}

# 7. ISO 26262-6:2018 Clause 10 — Software Integration & Verification (Tables 10–12)

Clause 10 focuses on integrating software units into components and verifying the integrated behavior against the architecture, hardware-software interface, and safety measures. Rust helps enforce interface correctness at compile time, but integration verification must also address timing, resources, and freedom from interference.

## 7.1 ISO 26262-6:2018 Table 10 — Methods for verification of software integration

{{TABLE: table-10}}

{{BLANK}}

## 7.2 ISO 26262-6:2018 Table 11 — Test case derivation for software integration testing

Use the same Table 8 derivation methods at the integration level, emphasizing interface boundaries and operational modes.

## 7.3 ISO 26262-6:2018 Table 12 — Structural coverage at the software architectural level

Architectural-level structural coverage focuses on functions/components being executed and call paths being exercised. For Rust, generic monomorphization means ‘function coverage’ must consider the relevant instantiations that appear in the final binary.

{{TABLE: table-11}}

{{BLANK}}

# 8. ISO 26262-6:2018 Clause 11 — Testing of Embedded Software (Tables 13–15)

Clause 11 validates the integrated embedded software in the target environment. While not Rust-specific, the coding standard should anticipate how Rust artifacts are exercised in HIL rigs, ECU networks, and vehicle tests.

## 8.1 ISO 26262-6:2018 Table 13 — Test environments

{{TABLE: table-12}}

{{BLANK}}

## 8.2 ISO 26262-6:2018 Table 14 — Methods for tests of embedded software

Requirements-based tests remain primary. For higher ASIL, fault injection at the software level is used to validate safety mechanisms (e.g., corrupted configuration/calibration parameters, injected communication errors).

## 8.3 ISO 26262-6:2018 Table 15 — Test case derivation for embedded software testing

Table 15 extends unit/integration derivation with functional dependency analysis and operational use cases. For Rust, explicitly include: boot/integrity checks, mode transitions, update mechanisms, and any HAL/driver edge cases.

# 9. Configurable Software (Annex C) and Rust Configuration Practices

Annex C addresses configuration and calibration data that influence embedded software behavior. Rust supports robust configuration handling through strong typing (newtypes), explicit parsing with validation, and compile-time configuration (feature flags, const generics) — but configurable behavior increases verification scope.

<!-- fmt: style="List Paragraph" -->
Treat configuration/calibration inputs as untrusted: validate ranges, cross-field constraints, and units at the boundary.

<!-- fmt: style="List Paragraph" -->
Represent configuration with typed structs and newtypes; avoid ‘stringly typed’ key-value access in safety-related code.

<!-- fmt: style="List Paragraph" -->
Prefer compile-time configuration for safety-critical variability when feasible (const generics, build-time features) to reduce runtime states — but control `#[cfg]` carefully to avoid untested variants.

<!-- fmt: style="List Paragraph" -->
Maintain separate safety cases and verification evidence for each configuration set intended for production release.

<!-- fmt: style="List Paragraph" -->
For ASIL C/D: configuration parsing and application logic should be in a dedicated module with high test coverage and boundary-value tests; consider formalizing constraints (contracts) for critical parameters.

# 10. Rust Language Inventory — Complete Construct Classification (QM to ASIL D)

This section provides a complete, auditable inventory of Rust language constructs as they appear in the source language. The intent is to classify every construct for use in a safety-related coding standard. Unstable/nightly features are treated as U (Unavailable) and therefore X for certified builds.

## 10.1 Global language-profile rules

<!-- fmt: style="List Paragraph" -->
Certified builds shall use stable Rust only (no `#![feature(...)]`).

<!-- fmt: style="List Paragraph" -->
Edition shall be pinned in Cargo.toml (this baseline assumes Edition 2024).

<!-- fmt: style="List Paragraph" -->
Application crates for ASIL code shall use `#![forbid(unsafe_code)]`. Unsafe is allowed only in explicitly named Q/TCB crates.

<!-- fmt: style="List Paragraph" -->
Panics shall not be used for expected errors. For ASIL C/D, `panic=abort` is required to avoid unwinding across boundaries.

<!-- fmt: style="List Paragraph" -->
All public safety-related APIs shall have explicit lifetimes (no lifetime elision) and explicit error semantics.

## 10.2 Keywords and lexical constructs (complete list)

Rust keywords are categorized as strict, reserved, and weak. Reserved keywords are not currently used but are prohibited as identifiers (except as raw identifiers). For safety-critical readability, use of raw identifiers (e.g., `r#try`) is restricted.

{{TABLE: table-13}}

{{BLANK}}

## 10.3 Items, modules, and visibility

Rust’s item system (modules, structs, enums, traits, impls) and visibility controls are the primary architectural tools for enforcing encapsulation and limiting interface size.

### Items and visibility

{{TABLE: table-14}}

{{BLANK}}

## 10.4 Types, generics, and lifetimes

Rust’s type system is a key safety mechanism. Restrictions primarily target platform-dependent types, unsafe-adjacent representations, and constructs that complicate reasoning (excessive generics, advanced lifetime features) without clear benefit.

### Type-system features

{{TABLE: table-15}}

{{BLANK}}

## 10.5 Control flow, patterns, and error propagation

Structured control flow supports verification. Rust lacks `goto`, but macros and divergence can still obscure flow. Error handling should be explicit (`Result`/`Option`), and panics should be reserved for unreachable invariant violations.

### Control flow and error propagation

{{TABLE: table-16}}

{{BLANK}}

## 10.6 Attributes, compiler configuration, and build directives

Attributes and build directives can significantly affect compiled behavior and verification scope. Safety profiles must restrict conditional compilation, representation attributes, and any attribute that changes linkage or memory layout.

### Attributes and configuration

{{TABLE: table-17}}

{{BLANK}}

## 10.7 Macros and compile-time code generation

Macros can hide control flow and data flow, impacting reviewability (Table 6 principle 1h). This mapping therefore uses an allowlist approach: standard macros are classified; custom macros are restricted.

### Macro usage

{{TABLE: table-18}}

{{BLANK}}

## 10.8 Unsafe Rust and undefined behavior boundaries

Unsafe Rust is the Trusted Computing Base (TCB) of a Rust safety argument. All unsafe usage must be minimized, isolated, and justified with documented invariants. For ASIL C/D, unsafe code is permitted only inside explicitly named Q modules with enhanced review and (where feasible) formal reasoning.

### Unsafe operations

{{TABLE: table-19}}

{{BLANK}}

# 11. Standard Library Inventory — core/alloc/std Modules and Macros (QM to ASIL D)

This section enumerates the complete module and macro surface of Rust 1.93.1’s `core`, `alloc`, and `std` crates, and classifies each area. For certified code, items marked Experimental/unstable are treated as U (Unavailable) and are not permitted.

<!-- fmt: size=10 -->
Notation for the ‘Profile’ column below:
• The profile is written as QM/A/B/C/D.
• Example: `P/P/R/R/R` means Permitted at QM and ASIL A, Restricted at ASIL B–D.

## 11.1 `core` crate module inventory (Rust 1.93.1)

{{TABLE: table-20}}

{{BLANK}}

## 11.2 `alloc` crate module inventory (Rust 1.93.1)

{{TABLE: table-21}}

{{BLANK}}

## 11.3 `std` crate module inventory (Rust 1.93.1)

{{TABLE: table-22}}

{{BLANK}}

## 11.4 Standard macros inventory (selected classification-critical)

Standard macros are imported by default and therefore must be explicitly classified. The list below covers the macros shown in Rust 1.93.1 standard library documentation. Macros not listed here are treated as prohibited for ASIL code by the default-deny rule.

{{TABLE: table-23}}

{{BLANK}}

## 11.5 Method-level rules for the standard library

Listing every method of every standard library type inside this document would be impractical, but certification still requires method-level decisions. This mapping therefore uses (1) a method hazard taxonomy that deterministically classifies methods, and (2) an explicit list of high-risk exceptions that are always restricted/prohibited.

### 11.5.1 Method hazard taxonomy (deterministic classification)

<!-- fmt: style="List Paragraph" -->
Panicking methods: any method documented to panic (including indexing via `Index`/`IndexMut`) is R for QM–B and X for ASIL C/D, unless proven unreachable and justified.

<!-- fmt: style="List Paragraph" -->
Allocating methods: any method that may allocate (Vec growth, String growth, format!, collecting into Vec) is P for QM–B with bounded capacity rules; R for ASIL C; and typically X for ASIL D unless allocator is qualified and determinism is shown.

<!-- fmt: style="List Paragraph" -->
OS-dependent methods: filesystem, networking, environment variables, process control, and system time are R for QM–B and Q/R for ASIL C/D (platform layer only).

<!-- fmt: style="List Paragraph" -->
Unsafe methods: any `unsafe fn` or method requiring `unsafe` is Q for ASIL C/D and forbidden in application crates.

<!-- fmt: style="List Paragraph" -->
Concurrency methods: any method that can block, lock, or spawn threads must have a bounded-time and deadlock policy; treat as R for ASIL B–D.

<!-- fmt: bold=true -->
Decision procedure (total mapping for every std/core/alloc function and method):

<!-- fmt: style="List Paragraph" size=9 -->
1) If the item is marked Experimental/unstable or requires nightly (`#![feature]`), classify as U (and therefore X for certified builds).

<!-- fmt: style="List Paragraph" size=9 -->
2) If calling the item requires `unsafe`, classify as Q for ASIL C/D (allowed only inside qualified TCB crates) and R for QM–B (enhanced review).

<!-- fmt: style="List Paragraph" size=9 -->
3) If the item can panic in a production build (documented panic or panicking precondition), classify as R for QM–B and X for ASIL C/D unless the panic is proven unreachable and justified as a fatal invariant.

<!-- fmt: style="List Paragraph" size=9 -->
4) If the item may allocate, classify by allocation policy: P for QM–B with bounded capacity + failure handling; R for ASIL C; and typically X for ASIL D unless a qualified allocator and determinism argument exists.

<!-- fmt: style="List Paragraph" size=9 -->
5) If the item interacts with OS/global state (filesystem, networking, env vars, processes, wall-clock time), classify as R for QM–B and Q/R for ASIL C/D (platform layer only).

<!-- fmt: style="List Paragraph" size=9 -->
6) If the item can block or introduce scheduling nondeterminism (locks, condvars, thread spawn, sleeps), classify as R for ASIL B–D unless bounded blocking and freedom-from-interference analysis is provided.

<!-- fmt: style="List Paragraph" size=9 -->
7) Otherwise, classify as P (Permitted), subject to the general coding rules (complexity limits, error handling, traceability).

### 11.5.2 Explicit high-risk API exceptions (always restricted/prohibited)

{{TABLE: table-24}}

{{BLANK}}

# 12. Tooling, Qualification, and Evidence Strategy (ISO 26262-8)

ISO 26262 relies on tools (compiler, static analysis, test/coverage tools) as part of the evidence chain. If tool output is used as safety evidence, the tool must be qualified to an appropriate confidence level, or alternative measures must compensate.

## 12.1 Compiler/toolchain qualification baseline

A qualification-oriented Rust language specification exists via the Ferrocene Language Specification (FLS), and Ferrocene provides qualified Rust toolchain distributions for safety-critical contexts. However, qualification is version-specific: a project must either use a qualified toolchain version, or perform its own qualification argument for the chosen compiler and standard library.

## 12.2 Tool roles and recommended evidence

{{TABLE: table-25}}

{{BLANK}}

## 12.3 Inventory automation (recommended)

To enforce completeness, generate the language/library inventory automatically in CI (e.g., via rustdoc JSON) and compare it to the approved allowlist captured by this document. Any delta (new modules, new APIs, removed APIs) triggers a mandatory review and an update to Sections 10–11.

# 13. ASIL Profile Summary Matrices

This section summarizes the most consequential profile differences by safety level. Project-specific tailoring is allowed with documented rationale, but ASIL D deviations should be rare and strongly justified.

{{TABLE: table-26}}

{{BLANK}}

# 14. References

<!-- fmt: style="List Paragraph" -->
ISO 26262:2018 — Road vehicles — Functional safety (all parts), with focus on ISO 26262-6 (software development) and ISO 26262-8 (supporting processes).

<!-- fmt: style="List Paragraph" -->
Rust Release Team. “Announcing Rust 1.93.1.” Rust Blog (Feb 12, 2026).

<!-- fmt: style="List Paragraph" -->
Rust Standard Library documentation for Rust 1.93.1: `std`, `core`, and `alloc` crates (doc.rust-lang.org).

<!-- fmt: style="List Paragraph" -->
The Rust Reference — Keywords (doc.rust-lang.org/reference/keywords.html).

<!-- fmt: style="List Paragraph" -->
Rust Edition Guide — Rust 2024 reserved syntax and `gen` keyword notes (doc.rust-lang.org/edition-guide/rust-2024/…).

<!-- fmt: style="List Paragraph" -->
Ferrocene Language Specification (FLS) repository (rust-lang/fls) and published spec (rust-lang.github.io/fls).

<!-- fmt: style="List Paragraph" -->
Ferrocene documentation and qualification information (ferrocene.dev; ferrous-systems.com blog posts on qualification).
