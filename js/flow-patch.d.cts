/** Types for flow-patch.cjs: atomic JSON flow patches, the same contract as tool/flow_patch.py. */
import type {FlowSpec, ValidFlow} from "./flow.cjs";

export type FlowPatchPath =
  | "/title"
  | "/sources_label"
  | `/${"sources" | "steps"}/${number}/${"title" | "note"}`;
export interface FlowPatchOperation {
  path: FlowPatchPath;
  value: string;
}
export interface FlowPatchDocument {
  spec: FlowSpec;
  /** At most 64 operations, applied all or nothing. */
  patch: FlowPatchOperation[];
}

/** Applies every operation, then validates the result; throws without partial changes. */
export function patchFlow(spec: FlowSpec, operations: FlowPatchOperation[]): ValidFlow;
/** ``{spec, patch}`` as one document (the CLI's stdin shape). */
export function applyDocument(document: FlowPatchDocument): ValidFlow;
