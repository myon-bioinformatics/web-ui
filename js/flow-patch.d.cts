/** Types for flow-patch.cjs. Mirrors tool/flow_patch.py. */
import type {FlowSpec, ValidFlow} from "./flow.cjs";
export type FlowPatchPath = "/title" | "/sources_label" | `/${"sources" | "steps"}/${number}/${"title" | "note"}`;
export interface FlowPatchOperation { path: FlowPatchPath; value: string }
export interface FlowPatchDocument { spec: FlowSpec; patch: FlowPatchOperation[] }
/** Applies all operations or none; throws Error on an invalid result. */
export function patchFlow(spec: FlowSpec, operations: FlowPatchOperation[]): ValidFlow;
export function applyDocument(document: FlowPatchDocument): ValidFlow;
