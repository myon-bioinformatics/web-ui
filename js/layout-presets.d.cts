/** Types for layout-presets.cjs: the same contract as tool/layout_presets.py. */
export const SCHEMA: "web-ui-layout-presets/1";
export const CANDIDATES: "web-ui-layout-candidates/1";

/** A --ui-* custom property name. */
export type LayoutVar = `--ui-${string}`;
export interface LayoutPreset {
  /** Lowercase token, unique: [a-z][a-z0-9-]{0,31}. */
  id: string;
  /** 1..60 characters. */
  label: string;
  /** Plain lengths only (px, rem, em, %, vw, fr, or 0); every preset sets the same names. */
  vars: Record<LayoutVar, string>;
  /** At most 120 characters. */
  note?: string;
}
export interface LayoutPresetSpec {
  schema: "web-ui-layout-presets/1";
  /** Defaults to the first preset. */
  default?: string;
  /** 1..12 presets. */
  presets: LayoutPreset[];
}
export interface ValidLayoutPresets {
  default: string;
  presets: Required<LayoutPreset>[];
}
/** What `layout_presets.py sweep` writes; only `schema` and `presets` are read here. */
export interface LayoutCandidates {
  schema: "web-ui-layout-candidates/1";
  default?: string;
  presets: Record<string, {passed: number[]; failed: number[]}>;
  by_width?: Record<string, string[]>;
  every_width_has_a_candidate?: boolean;
  observations?: {preset: string; width: number; ok: boolean; failed: string[]; items: number}[];
}

/** Checks any value against the contract; throws Error otherwise. */
export function validate(spec: unknown): ValidLayoutPresets;
/** The default preset on :root, then one body:has(radio:checked) rule per preset. */
export function css(spec: LayoutPresetSpec): string;
/** Radio controls, default checked; with candidates, labels each preset "ok at …" / "check at …". */
export function controlsHtml(spec: LayoutPresetSpec, candidates?: LayoutCandidates | null, legend?: string): string;
