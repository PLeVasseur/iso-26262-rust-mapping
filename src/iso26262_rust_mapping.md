{dp}`SRCN-00000000000000000000000000000001` {ts}`unmapped_with_rationale`
ISO 26262-6:2018 to Rust 1.93.1

{dp}`SRCN-00000000000000000000000000000002` {ts}`unmapped_with_rationale`
Complete Language and Standard Library Mapping

{dp}`SRCN-00000000000000000000000000000003` {ts}`unmapped_with_rationale`
Reference for Safety-Critical Rust Coding Standards (QM to ASIL D)

{dp}`SRCN-00000000000000000000000000000004` {ts}`unmapped_with_rationale`
Revision 2 — February 2026

{dp}`SRCN-00000000000000000000000000000005` {ts}`unmapped_with_rationale`
Working reference for Safety-Critical Rust Consortium — Coding Guidelines Subcommittee

{dp}`SRCN-00000000000000000000000000000006` {ts}`unmapped_with_rationale`
Baseline: Rust stable 1.93.1 (2026-02-12), Edition 2024 (no nightly features)

# Table of Contents

{dp}`SRCN-00000000000000000000000000000007` {ts}`unmapped_with_rationale`
Note: This document uses Word heading styles. To generate an automatic table of contents, insert a TOC field in Word and update.

{dp}`SRCN-00000000000000000000000000000008` {ts}`unmapped_with_rationale`
1\. Introduction and Scope

{dp}`SRCN-00000000000000000000000000000009` {ts}`unmapped_with_rationale`
2\. Review Notes and Critiques of Draft v1

{dp}`SRCN-0000000000000000000000000000000A` {ts}`unmapped_with_rationale`
3\. ISO 26262-6:2018 Clause 5 — General Topics & Table 1 (Topics for Modelling/Coding Guidelines)

{dp}`SRCN-0000000000000000000000000000000B` {ts}`unmapped_with_rationale`
4\. ISO 26262-6:2018 Clause 7 — Software Architectural Design (Tables 2–4)

{dp}`SRCN-0000000000000000000000000000000C` {ts}`unmapped_with_rationale`
5\. ISO 26262-6:2018 Clause 8 — Software Unit Design & Implementation (Tables 5–6)

{dp}`SRCN-0000000000000000000000000000000D` {ts}`unmapped_with_rationale`
6\. ISO 26262-6:2018 Clause 9 — Software Unit Verification (Tables 7–9)

{dp}`SRCN-0000000000000000000000000000000E` {ts}`unmapped_with_rationale`
7\. ISO 26262-6:2018 Clause 10 — Software Integration & Verification (Tables 10–12)

{dp}`SRCN-0000000000000000000000000000000F` {ts}`unmapped_with_rationale`
8\. ISO 26262-6:2018 Clause 11 — Testing of Embedded Software (Tables 13–15)

{dp}`SRCN-00000000000000000000000000000010` {ts}`unmapped_with_rationale`
9\. Configurable Software (Annex C) and Rust Configuration Practices

{dp}`SRCN-00000000000000000000000000000011` {ts}`unmapped_with_rationale`
10\. Rust Language Inventory — Complete Construct Classification (QM to ASIL D)

{dp}`SRCN-00000000000000000000000000000012` {ts}`unmapped_with_rationale`
11\. Standard Library Inventory — core/alloc/std Modules and Macros (QM to ASIL D)

{dp}`SRCN-00000000000000000000000000000013` {ts}`unmapped_with_rationale`
12\. Tooling, Qualification, and Evidence Strategy (ISO 26262-8)

{dp}`SRCN-00000000000000000000000000000014` {ts}`unmapped_with_rationale`
13\. ASIL Profile Summary Matrices

{dp}`SRCN-00000000000000000000000000000015` {ts}`unmapped_with_rationale`
14\. References

# 1. Introduction and Scope

{dp}`SRCN-00000000000000000000000000000016` {ts}`unmapped_with_rationale`
This document maps ISO 26262:2018 (Road vehicles — Functional safety) software development expectations onto the Rust programming language and its standard library. It is intended to be used as an input to a project- or consortium-specific coding standard, and to support a defensible safety case (QM through ASIL D) for Rust-based automotive software.

## 1.1 Normative baselines and versioning

{dp}`SRCN-00000000000000000000000000000017` {ts}`unmapped_with_rationale`
All technical guidance in this revision is anchored to the following baselines:
• ISO 26262-6:2018 clauses and tables (software development at the software level).
• Rust stable 1.93.1 standard library documentation (std/core/alloc) and Rust Reference keywords.
• Ferrocene Language Specification (FLS) as the qualification-oriented normative description of Rust language behavior, where applicable.

{dp}`SRCN-00000000000000000000000000000018` {ts}`unmapped_with_rationale`
Because Rust evolves, this mapping is explicitly versioned. Any change to the Rust toolchain version, the Edition, or the set of approved dependencies requires re-assessing the impacted rows in the inventories in Sections 10–11 and updating the safety argument.

## 1.2 QM and ASIL applicability

{dp}`SRCN-00000000000000000000000000000019` {ts}`unmapped_with_rationale`
ISO 26262 defines four Automotive Safety Integrity Levels (ASIL A–D) and a non-safety classification QM (Quality Management). QM items do not impose ISO 26262 safety requirements, but they still benefit from the same disciplined engineering practices. This document therefore provides a graded profile from QM (least restrictive) to ASIL D (most restrictive).

## 1.3 Interpretation of ISO 26262 table symbols

{dp}`SRCN-0000000000000000000000000000001A` {ts}`unmapped_with_rationale`
ISO 26262 tables classify methods and principles using symbols:
• “++” = highly recommended
• “+” = recommended
• “o” = neither recommended nor discouraged
and some clauses apply to ASIL values shown in parentheses as recommendations rather than requirements. This mapping preserves the intent by translating it into enforceable rules and evidence expectations.

## 1.4 Classification codes used in this mapping

{dp}`SRCN-0000000000000000000000000000001B` {ts}`unmapped_with_rationale`
Every Rust language construct, standard library module, or API surface is classified per safety level using the following codes:
• P  — Permitted (allowed without additional justification beyond normal review/testing)
• HR — Highly recommended (preferred default)
• M  — Mandatory (required when applicable)
• R  — Restricted (allowed only under stated constraints and documented rationale)
• Q  — Qualified-only / Trusted component (allowed only inside pre-approved, independently reviewed ‘TCB’ modules such as HAL/FFI/allocator)
• X  — Prohibited (not allowed in certified code)
• U  — Unavailable/unstable/experimental (not allowed in certified builds; requires nightly or non-qualified behavior)

## 1.5 Completeness rule and default-deny policy

{dp}`SRCN-0000000000000000000000000000001C` {ts}`unmapped_with_rationale`
Completeness is enforced by a default-deny rule: any Rust feature, attribute, macro, or standard library API not explicitly classified in Sections 10–11 is treated as X (Prohibited) for ASIL code, until reviewed and added. QM may optionally operate with default-allow, but doing so weakens re-use across ASIL levels; therefore, this document recommends using the same default-deny mechanism for all safety levels.

{dp}`SRCN-0000000000000000000000000000001D` {ts}`unmapped_with_rationale`
To keep the inventories complete as Rust evolves, projects should generate an automated API inventory (e.g., from rustdoc JSON) during CI and compare it against the approved allowlist. Any delta (new or removed items) must trigger a review and a documented mapping update.

## 1.6 ISO 26262-6:2018 clause and table cross-reference

{dp}`SRCN-0000000000000000000000000000001E` {ts}`unmapped_with_rationale`
This section provides an explicit mapping between the structure of this Rust language/library mapping and the corresponding ISO 26262-6:2018 clauses, tables, and annexes referenced throughout.

```{iso-table} table-01
:caption: ISO mapping table-01
:label: table-01
```

# 2. Review Notes and Critiques of Draft v1

{dp}`SRCN-0000000000000000000000000000001F` {ts}`unmapped_with_rationale`
This revision started from a prior internal draft and applies several corrective and completeness-driven improvements. The critiques below are intended to be constructive review feedback and to explain why the document was restructured.

{dp}`SRCN-00000000000000000000000000000020` {ts}`unmapped_with_rationale`
ISO 26262 table alignment: multiple tables were mis-numbered or mapped to the wrong content. For example, ISO 26262-6 Table 1 concerns topics for modelling/coding guidelines; architectural design principles are in Table 3, and unit design principles are in Table 6. Structural coverage metrics for unit testing are in Table 9; function/call coverage at the architectural level is Table 12.

{dp}`SRCN-00000000000000000000000000000021` {ts}`unmapped_with_rationale`
Missing ISO topics: Table 1 includes an explicit concurrency topic (1i) which must be addressed by coding guidelines; earlier drafts focused on concurrency later but did not trace it back to Table 1.

{dp}`SRCN-00000000000000000000000000000022` {ts}`unmapped_with_rationale`
Incomplete inventory: the standard library mapping covered only a subset of core/std modules and did not enumerate the full module/macro surface of Rust 1.93.1 (including experimental and deprecation-planned areas). A complete mapping must start from a complete inventory.

{dp}`SRCN-00000000000000000000000000000023` {ts}`unmapped_with_rationale`
Insufficient QM coverage: earlier drafts began at ASIL A; this revision adds QM as an explicit profile and clarifies which restrictions are safety-motivated vs general quality-driven.

{dp}`SRCN-00000000000000000000000000000024` {ts}`unmapped_with_rationale`
Ambiguity around panics and unwinding: earlier drafts discussed unwrap/expect but did not specify a complete panic policy (panic=abort vs unwind), FFI boundaries, or how panic-related APIs in std/core are treated per ASIL.

{dp}`SRCN-00000000000000000000000000000025` {ts}`unmapped_with_rationale`
Unclear governance: a complete mapping must include an update mechanism (default-deny + automated inventory diff) so that new Rust releases or new dependencies cannot silently bypass the coding standard.

{dp}`SRCN-00000000000000000000000000000026` {ts}`unmapped_with_rationale`
All subsequent sections incorporate these corrections and extend the mapping to a complete module/macro inventory for core/alloc/std as of Rust 1.93.1.

# 3. ISO 26262-6:2018 Clause 5 — General Topics & Table 1

{dp}`SRCN-00000000000000000000000000000027` {ts}`unmapped_with_rationale`
ISO 26262-6 Clause 5 establishes expectations for the software development process and environment, including the selection of modelling/design/programming languages and the use of guidelines. Table 1 lists the topics that coding/modelling guidelines should cover. In Rust, many of these topics are partially satisfied by the language design (ownership, typing, safe/unsafe boundary), but they still require explicit project rules, tool configuration, and evidence.

## 3.1 ISO 26262-6:2018 Table 1 — Topics to be covered by modelling and coding guidelines

```{iso-table} table-02
:caption: ISO mapping table-02
:label: table-02
```

# 4. ISO 26262-6:2018 Clause 7 — Software Architectural Design (Tables 2–4)

{dp}`SRCN-00000000000000000000000000000028` {ts}`unmapped_with_rationale`
Clause 7 focuses on constructing and verifying a software architecture that satisfies software safety requirements and supports implementation and verification. The architecture must capture static aspects (component structure, interfaces, data types) and dynamic aspects (control flow, concurrency, timing).

## 4.1 ISO 26262-6:2018 Table 2 — Notations for software architectural design

{dp}`SRCN-00000000000000000000000000000029` {ts}`unmapped_with_rationale`
Rust does not prescribe a single architectural notation, but it provides strong support for architecture documentation through explicit module boundaries, visibility control, and auto-generated API documentation (rustdoc). For ASIL C/D, semi-formal representations (state machines, sequence diagrams, timing models) are typically needed alongside rustdoc.

```{iso-table} table-03
:caption: ISO mapping table-03
:label: table-03
```

## 4.2 ISO 26262-6:2018 Table 3 — Architectural design principles mapped to Rust

{dp}`SRCN-0000000000000000000000000000002A` {ts}`unmapped_with_rationale`
Table 3 architectural principles map naturally to Rust’s crate/module system and to explicit interface boundaries. The key safety contribution is to keep components small, cohesive, and isolated, and to manage shared resources and timing determinism explicitly.

```{iso-table} table-04
:caption: ISO mapping table-04
:label: table-04
```

## 4.3 ISO 26262-6:2018 Table 4 — Verification methods for the software architectural design

{dp}`SRCN-0000000000000000000000000000002B` {ts}`unmapped_with_rationale`
Table 4 lists verification methods (walk-through, inspection, simulation, prototype generation, formal verification, control/data flow analysis, scheduling analysis). In Rust projects, these map to architecture reviews, static analysis, model-based simulations (where applicable), and timing/resource analysis.

```{iso-table} table-05
:caption: ISO mapping table-05
:label: table-05
```

# 5. ISO 26262-6:2018 Clause 8 — Software Unit Design & Implementation (Tables 5–6)

{dp}`SRCN-0000000000000000000000000000002C` {ts}`unmapped_with_rationale`
Clause 8 focuses on unit-level design and implementation rules that prevent systematic faults and produce verifiable, readable source code. Rust eliminates some C/C++ failure modes by construction, but Clause 8 still requires explicit coding rules, especially for allocation, unsafe code, macros, and error handling.

## 5.1 ISO 26262-6:2018 Table 5 — Notations for software unit design

{dp}`SRCN-0000000000000000000000000000002D` {ts}`unmapped_with_rationale`
Unit-level design descriptions should be detailed enough to support implementation and verification. In Rust, this typically means:
• module-level docs describing responsibilities and invariants,
• state machine definitions (enums + transitions),
• interface contracts (preconditions/postconditions), and
• data structure invariants (including unsafe invariants when applicable).

## 5.2 ISO 26262-6:2018 Table 6 — Design principles for software unit design and implementation

```{iso-table} table-06
:caption: ISO mapping table-06
:label: table-06
```

# 6. ISO 26262-6:2018 Clause 9 — Software Unit Verification (Tables 7–9)

{dp}`SRCN-0000000000000000000000000000002E` {ts}`unmapped_with_rationale`
Clause 9 requires evidence that the unit design and implementation satisfy allocated requirements, implement safety measures, and contain neither unintended functionality nor unsafe properties. Rust contributes via strong static guarantees (initialization, borrow checking, data-race freedom in safe code), but verification still requires reviews, static analysis, testing, and coverage evidence.

## 6.1 ISO 26262-6:2018 Table 7 — Methods for software unit verification mapped to Rust

```{iso-table} table-07
:caption: ISO mapping table-07
:label: table-07
```

## 6.2 ISO 26262-6:2018 Table 8 — Test case derivation methods for unit testing

{dp}`SRCN-0000000000000000000000000000002F` {ts}`unmapped_with_rationale`
Rust unit tests should be derived systematically, not ad hoc. Table 8’s methods map well to typical Rust testing practices.

```{iso-table} table-08
:caption: ISO mapping table-08
:label: table-08
```

## 6.3 ISO 26262-6:2018 Table 9 — Structural coverage metrics at the software unit level

{dp}`SRCN-00000000000000000000000000000030` {ts}`unmapped_with_rationale`
Table 9 requires measurement of unit-level structural coverage. For Rust, coverage tools must account for monomorphization, inlining, and compiler-generated code. For ASIL D, MC/DC is typically required and may need specialized tooling and test design.

```{iso-table} table-09
:caption: ISO mapping table-09
:label: table-09
```

# 7. ISO 26262-6:2018 Clause 10 — Software Integration & Verification (Tables 10–12)

{dp}`SRCN-00000000000000000000000000000031` {ts}`unmapped_with_rationale`
Clause 10 focuses on integrating software units into components and verifying the integrated behavior against the architecture, hardware-software interface, and safety measures. Rust helps enforce interface correctness at compile time, but integration verification must also address timing, resources, and freedom from interference.

## 7.1 ISO 26262-6:2018 Table 10 — Methods for verification of software integration

```{iso-table} table-10
:caption: ISO mapping table-10
:label: table-10
```

## 7.2 ISO 26262-6:2018 Table 11 — Test case derivation for software integration testing

{dp}`SRCN-00000000000000000000000000000032` {ts}`unmapped_with_rationale`
Use the same Table 8 derivation methods at the integration level, emphasizing interface boundaries and operational modes.

## 7.3 ISO 26262-6:2018 Table 12 — Structural coverage at the software architectural level

{dp}`SRCN-00000000000000000000000000000033` {ts}`unmapped_with_rationale`
Architectural-level structural coverage focuses on functions/components being executed and call paths being exercised. For Rust, generic monomorphization means ‘function coverage’ must consider the relevant instantiations that appear in the final binary.

```{iso-table} table-11
:caption: ISO mapping table-11
:label: table-11
```

# 8. ISO 26262-6:2018 Clause 11 — Testing of Embedded Software (Tables 13–15)

{dp}`SRCN-00000000000000000000000000000034` {ts}`unmapped_with_rationale`
Clause 11 validates the integrated embedded software in the target environment. While not Rust-specific, the coding standard should anticipate how Rust artifacts are exercised in HIL rigs, ECU networks, and vehicle tests.

## 8.1 ISO 26262-6:2018 Table 13 — Test environments

```{iso-table} table-12
:caption: ISO mapping table-12
:label: table-12
```

## 8.2 ISO 26262-6:2018 Table 14 — Methods for tests of embedded software

{dp}`SRCN-00000000000000000000000000000035` {ts}`unmapped_with_rationale`
Requirements-based tests remain primary. For higher ASIL, fault injection at the software level is used to validate safety mechanisms (e.g., corrupted configuration/calibration parameters, injected communication errors).

## 8.3 ISO 26262-6:2018 Table 15 — Test case derivation for embedded software testing

{dp}`SRCN-00000000000000000000000000000036` {ts}`unmapped_with_rationale`
Table 15 extends unit/integration derivation with functional dependency analysis and operational use cases. For Rust, explicitly include: boot/integrity checks, mode transitions, update mechanisms, and any HAL/driver edge cases.

# 9. Configurable Software (Annex C) and Rust Configuration Practices

{dp}`SRCN-00000000000000000000000000000037` {ts}`unmapped_with_rationale`
Annex C addresses configuration and calibration data that influence embedded software behavior. Rust supports robust configuration handling through strong typing (newtypes), explicit parsing with validation, and compile-time configuration (feature flags, const generics) — but configurable behavior increases verification scope.

{dp}`SRCN-00000000000000000000000000000038` {ts}`unmapped_with_rationale`
Treat configuration/calibration inputs as untrusted: validate ranges, cross-field constraints, and units at the boundary.

{dp}`SRCN-00000000000000000000000000000039` {ts}`unmapped_with_rationale`
Represent configuration with typed structs and newtypes; avoid ‘stringly typed’ key-value access in safety-related code.

{dp}`SRCN-0000000000000000000000000000003A` {ts}`unmapped_with_rationale`
Prefer compile-time configuration for safety-critical variability when feasible (const generics, build-time features) to reduce runtime states — but control `#[cfg]` carefully to avoid untested variants.

{dp}`SRCN-0000000000000000000000000000003B` {ts}`unmapped_with_rationale`
Maintain separate safety cases and verification evidence for each configuration set intended for production release.

{dp}`SRCN-0000000000000000000000000000003C` {ts}`unmapped_with_rationale`
For ASIL C/D: configuration parsing and application logic should be in a dedicated module with high test coverage and boundary-value tests; consider formalizing constraints (contracts) for critical parameters.

# 10. Rust Language Inventory — Complete Construct Classification (QM to ASIL D)

{dp}`SRCN-0000000000000000000000000000003D` {ts}`unmapped_with_rationale`
This section provides a complete, auditable inventory of Rust language constructs as they appear in the source language. The intent is to classify every construct for use in a safety-related coding standard. Unstable/nightly features are treated as U (Unavailable) and therefore X for certified builds.

## 10.1 Global language-profile rules

{dp}`SRCN-0000000000000000000000000000003E` {ts}`unmapped_with_rationale`
Certified builds shall use stable Rust only (no `#![feature(...)]`).

{dp}`SRCN-0000000000000000000000000000003F` {ts}`unmapped_with_rationale`
Edition shall be pinned in Cargo.toml (this baseline assumes Edition 2024).

{dp}`SRCN-00000000000000000000000000000040` {ts}`unmapped_with_rationale`
Application crates for ASIL code shall use `#![forbid(unsafe_code)]`. Unsafe is allowed only in explicitly named Q/TCB crates.

{dp}`SRCN-00000000000000000000000000000041` {ts}`unmapped_with_rationale`
Panics shall not be used for expected errors. For ASIL C/D, `panic=abort` is required to avoid unwinding across boundaries.

{dp}`SRCN-00000000000000000000000000000042` {ts}`unmapped_with_rationale`
All public safety-related APIs shall have explicit lifetimes (no lifetime elision) and explicit error semantics.

## 10.2 Keywords and lexical constructs (complete list)

{dp}`SRCN-00000000000000000000000000000043` {ts}`unmapped_with_rationale`
Rust keywords are categorized as strict, reserved, and weak. Reserved keywords are not currently used but are prohibited as identifiers (except as raw identifiers). For safety-critical readability, use of raw identifiers (e.g., `r#try`) is restricted.

```{iso-table} table-13
:caption: ISO mapping table-13
:label: table-13
```

## 10.3 Items, modules, and visibility

{dp}`SRCN-00000000000000000000000000000044` {ts}`unmapped_with_rationale`
Rust’s item system (modules, structs, enums, traits, impls) and visibility controls are the primary architectural tools for enforcing encapsulation and limiting interface size.

### Items and visibility

```{iso-table} table-14
:caption: ISO mapping table-14
:label: table-14
```

## 10.4 Types, generics, and lifetimes

{dp}`SRCN-00000000000000000000000000000045` {ts}`unmapped_with_rationale`
Rust’s type system is a key safety mechanism. Restrictions primarily target platform-dependent types, unsafe-adjacent representations, and constructs that complicate reasoning (excessive generics, advanced lifetime features) without clear benefit.

### Type-system features

```{iso-table} table-15
:caption: ISO mapping table-15
:label: table-15
```

## 10.5 Control flow, patterns, and error propagation

{dp}`SRCN-00000000000000000000000000000046` {ts}`unmapped_with_rationale`
Structured control flow supports verification. Rust lacks `goto`, but macros and divergence can still obscure flow. Error handling should be explicit (`Result`/`Option`), and panics should be reserved for unreachable invariant violations.

### Control flow and error propagation

```{iso-table} table-16
:caption: ISO mapping table-16
:label: table-16
```

## 10.6 Attributes, compiler configuration, and build directives

{dp}`SRCN-00000000000000000000000000000047` {ts}`unmapped_with_rationale`
Attributes and build directives can significantly affect compiled behavior and verification scope. Safety profiles must restrict conditional compilation, representation attributes, and any attribute that changes linkage or memory layout.

### Attributes and configuration

```{iso-table} table-17
:caption: ISO mapping table-17
:label: table-17
```

## 10.7 Macros and compile-time code generation

{dp}`SRCN-00000000000000000000000000000048` {ts}`unmapped_with_rationale`
Macros can hide control flow and data flow, impacting reviewability (Table 6 principle 1h). This mapping therefore uses an allowlist approach: standard macros are classified; custom macros are restricted.

### Macro usage

```{iso-table} table-18
:caption: ISO mapping table-18
:label: table-18
```

## 10.8 Unsafe Rust and undefined behavior boundaries

{dp}`SRCN-00000000000000000000000000000049` {ts}`unmapped_with_rationale`
Unsafe Rust is the Trusted Computing Base (TCB) of a Rust safety argument. All unsafe usage must be minimized, isolated, and justified with documented invariants. For ASIL C/D, unsafe code is permitted only inside explicitly named Q modules with enhanced review and (where feasible) formal reasoning.

### Unsafe operations

```{iso-table} table-19
:caption: ISO mapping table-19
:label: table-19
```

# 11. Standard Library Inventory — core/alloc/std Modules and Macros (QM to ASIL D)

{dp}`SRCN-0000000000000000000000000000004A` {ts}`unmapped_with_rationale`
This section enumerates the complete module and macro surface of Rust 1.93.1’s `core`, `alloc`, and `std` crates, and classifies each area. For certified code, items marked Experimental/unstable are treated as U (Unavailable) and are not permitted.

{dp}`SRCN-0000000000000000000000000000004B` {ts}`unmapped_with_rationale`
Notation for the ‘Profile’ column below:
• The profile is written as QM/A/B/C/D.
• Example: `P/P/R/R/R` means Permitted at QM and ASIL A, Restricted at ASIL B–D.

## 11.1 `core` crate module inventory (Rust 1.93.1)

```{iso-table} table-20
:caption: ISO mapping table-20
:label: table-20
```

## 11.2 `alloc` crate module inventory (Rust 1.93.1)

```{iso-table} table-21
:caption: ISO mapping table-21
:label: table-21
```

## 11.3 `std` crate module inventory (Rust 1.93.1)

```{iso-table} table-22
:caption: ISO mapping table-22
:label: table-22
```

## 11.4 Standard macros inventory (selected classification-critical)

{dp}`SRCN-0000000000000000000000000000004C` {ts}`unmapped_with_rationale`
Standard macros are imported by default and therefore must be explicitly classified. The list below covers the macros shown in Rust 1.93.1 standard library documentation. Macros not listed here are treated as prohibited for ASIL code by the default-deny rule.

```{iso-table} table-23
:caption: ISO mapping table-23
:label: table-23
```

## 11.5 Method-level rules for the standard library

{dp}`SRCN-0000000000000000000000000000004D` {ts}`unmapped_with_rationale`
Listing every method of every standard library type inside this document would be impractical, but certification still requires method-level decisions. This mapping therefore uses (1) a method hazard taxonomy that deterministically classifies methods, and (2) an explicit list of high-risk exceptions that are always restricted/prohibited.

### 11.5.1 Method hazard taxonomy (deterministic classification)

{dp}`SRCN-0000000000000000000000000000004E` {ts}`unmapped_with_rationale`
Panicking methods: any method documented to panic (including indexing via `Index`/`IndexMut`) is R for QM–B and X for ASIL C/D, unless proven unreachable and justified.

{dp}`SRCN-0000000000000000000000000000004F` {ts}`unmapped_with_rationale`
Allocating methods: any method that may allocate (Vec growth, String growth, format!, collecting into Vec) is P for QM–B with bounded capacity rules; R for ASIL C; and typically X for ASIL D unless allocator is qualified and determinism is shown.

{dp}`SRCN-00000000000000000000000000000050` {ts}`unmapped_with_rationale`
OS-dependent methods: filesystem, networking, environment variables, process control, and system time are R for QM–B and Q/R for ASIL C/D (platform layer only).

{dp}`SRCN-00000000000000000000000000000051` {ts}`unmapped_with_rationale`
Unsafe methods: any `unsafe fn` or method requiring `unsafe` is Q for ASIL C/D and forbidden in application crates.

{dp}`SRCN-00000000000000000000000000000052` {ts}`unmapped_with_rationale`
Concurrency methods: any method that can block, lock, or spawn threads must have a bounded-time and deadlock policy; treat as R for ASIL B–D.

{dp}`SRCN-00000000000000000000000000000053` {ts}`unmapped_with_rationale`
Decision procedure (total mapping for every std/core/alloc function and method):

{dp}`SRCN-00000000000000000000000000000054` {ts}`unmapped_with_rationale`
1\) If the item is marked Experimental/unstable or requires nightly (`#![feature]`), classify as U (and therefore X for certified builds).

{dp}`SRCN-00000000000000000000000000000055` {ts}`unmapped_with_rationale`
2\) If calling the item requires `unsafe`, classify as Q for ASIL C/D (allowed only inside qualified TCB crates) and R for QM–B (enhanced review).

{dp}`SRCN-00000000000000000000000000000056` {ts}`unmapped_with_rationale`
3\) If the item can panic in a production build (documented panic or panicking precondition), classify as R for QM–B and X for ASIL C/D unless the panic is proven unreachable and justified as a fatal invariant.

{dp}`SRCN-00000000000000000000000000000057` {ts}`unmapped_with_rationale`
4\) If the item may allocate, classify by allocation policy: P for QM–B with bounded capacity + failure handling; R for ASIL C; and typically X for ASIL D unless a qualified allocator and determinism argument exists.

{dp}`SRCN-00000000000000000000000000000058` {ts}`unmapped_with_rationale`
5\) If the item interacts with OS/global state (filesystem, networking, env vars, processes, wall-clock time), classify as R for QM–B and Q/R for ASIL C/D (platform layer only).

{dp}`SRCN-00000000000000000000000000000059` {ts}`unmapped_with_rationale`
6\) If the item can block or introduce scheduling nondeterminism (locks, condvars, thread spawn, sleeps), classify as R for ASIL B–D unless bounded blocking and freedom-from-interference analysis is provided.

{dp}`SRCN-0000000000000000000000000000005A` {ts}`unmapped_with_rationale`
7\) Otherwise, classify as P (Permitted), subject to the general coding rules (complexity limits, error handling, traceability).

### 11.5.2 Explicit high-risk API exceptions (always restricted/prohibited)

```{iso-table} table-24
:caption: ISO mapping table-24
:label: table-24
```

# 12. Tooling, Qualification, and Evidence Strategy (ISO 26262-8)

{dp}`SRCN-0000000000000000000000000000005B` {ts}`unmapped_with_rationale`
ISO 26262 relies on tools (compiler, static analysis, test/coverage tools) as part of the evidence chain. If tool output is used as safety evidence, the tool must be qualified to an appropriate confidence level, or alternative measures must compensate.

## 12.1 Compiler/toolchain qualification baseline

{dp}`SRCN-0000000000000000000000000000005C` {ts}`unmapped_with_rationale`
A qualification-oriented Rust language specification exists via the Ferrocene Language Specification (FLS), and Ferrocene provides qualified Rust toolchain distributions for safety-critical contexts. However, qualification is version-specific: a project must either use a qualified toolchain version, or perform its own qualification argument for the chosen compiler and standard library.

## 12.2 Tool roles and recommended evidence

```{iso-table} table-25
:caption: ISO mapping table-25
:label: table-25
```

## 12.3 Inventory automation (recommended)

{dp}`SRCN-0000000000000000000000000000005D` {ts}`unmapped_with_rationale`
To enforce completeness, generate the language/library inventory automatically in CI (e.g., via rustdoc JSON) and compare it to the approved allowlist captured by this document. Any delta (new modules, new APIs, removed APIs) triggers a mandatory review and an update to Sections 10–11.

# 13. ASIL Profile Summary Matrices

{dp}`SRCN-0000000000000000000000000000005E` {ts}`unmapped_with_rationale`
This section summarizes the most consequential profile differences by safety level. Project-specific tailoring is allowed with documented rationale, but ASIL D deviations should be rare and strongly justified.

```{iso-table} table-26
:caption: ISO mapping table-26
:label: table-26
```

# 14. References

{dp}`SRCN-0000000000000000000000000000005F` {ts}`unmapped_with_rationale`
ISO 26262:2018 — Road vehicles — Functional safety (all parts), with focus on ISO 26262-6 (software development) and ISO 26262-8 (supporting processes).

{dp}`SRCN-00000000000000000000000000000060` {ts}`unmapped_with_rationale`
Rust Release Team. “Announcing Rust 1.93.1.” Rust Blog (Feb 12, 2026).

{dp}`SRCN-00000000000000000000000000000061` {ts}`unmapped_with_rationale`
Rust Standard Library documentation for Rust 1.93.1: `std`, `core`, and `alloc` crates (doc.rust-lang.org).

{dp}`SRCN-00000000000000000000000000000062` {ts}`unmapped_with_rationale`
The Rust Reference — Keywords (doc.rust-lang.org/reference/keywords.html).

{dp}`SRCN-00000000000000000000000000000063` {ts}`unmapped_with_rationale`
Rust Edition Guide — Rust 2024 reserved syntax and `gen` keyword notes (doc.rust-lang.org/edition-guide/rust-2024/…).

{dp}`SRCN-00000000000000000000000000000064` {ts}`unmapped_with_rationale`
Ferrocene Language Specification (FLS) repository (rust-lang/fls) and published spec (rust-lang.github.io/fls).

{dp}`SRCN-00000000000000000000000000000065` {ts}`unmapped_with_rationale`
Ferrocene documentation and qualification information (ferrocene.dev; ferrous-systems.com blog posts on qualification).
