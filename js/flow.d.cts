/** Types for flow.cjs. Mirrors tool/flow_diagram.py; validation still happens at run time. */
export interface FlowCard { title: string; note?: string }
export interface FlowSpec { title?: string; sources_label?: string; sources: FlowCard[]; steps: FlowCard[] }
export interface ValidFlowCard { title: string; note: string }
export interface ValidFlow { title: string; sources_label: string; sources: ValidFlowCard[]; steps: ValidFlowCard[] }
export type FlowTheme = "modern" | "github-like";
/** Checked copy with defaults filled in; throws Error on any invalid field. */
export function validate(spec: unknown): ValidFlow;
export function flowHtml(spec: FlowSpec): string;
/** A fenced ```mermaid block ending with a newline. */
export function flowMermaid(spec: FlowSpec): string;
export function flowDocument(spec: FlowSpec, theme?: FlowTheme): string;
