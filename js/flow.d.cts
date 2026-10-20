/**
 * Types for flow.cjs: the JSON flow contract shared with web_ui.py and tool/flow_diagram.py.
 * Declarations only; flow.cjs stays plain JavaScript. Every function validates at run time.
 */
export interface FlowCard {
  /** 1..120 code points, not blank, no control characters. */
  title: string;
  /** 0..240 code points. */
  note?: string;
}
export interface FlowSpec {
  /** 1..120 code points, not blank. */
  title: string;
  /** Defaults to "Sources". */
  sources_label?: string;
  /** 1..8 cards. */
  sources: FlowCard[];
  /** 1..8 cards. */
  steps: FlowCard[];
}
/** A validated flow: defaults filled in, every card has a note ("" when absent). */
export interface ValidFlow {
  title: string;
  sources_label: string;
  sources: Required<FlowCard>[];
  steps: Required<FlowCard>[];
}
export type FlowTheme = "modern" | "github-like";

/** Checks any value against the contract; throws Error("invalid ...") otherwise. */
export function validate(spec: unknown): ValidFlow;
/** The flow as an escaped HTML figure (no script). */
export function flowHtml(spec: FlowSpec): string;
/** The flow as a fenced Mermaid flowchart block. */
export function flowMermaid(spec: FlowSpec): string;
/** A standalone HTML page linking ./css/*.css and the chosen theme. */
export function flowDocument(spec: FlowSpec, theme?: FlowTheme): string;
