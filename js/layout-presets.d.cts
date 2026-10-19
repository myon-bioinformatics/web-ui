/** Types for layout-presets.cjs. Mirrors tool/layout_presets.py (css and controls are byte-identical). */
export const SCHEMA: "web-ui-layout-presets/1";
export const CANDIDATES: "web-ui-layout-candidates/1";
/** A plain CSS length such as "8px", "1.5rem" or "1fr". */
export type LayoutLength = string;
export interface LayoutPreset { id: string; label: string; vars: Record<`--ui-${string}`, LayoutLength>; note?: string }
export interface LayoutPresets { schema: typeof SCHEMA; default?: string; presets: LayoutPreset[] }
export interface ValidLayoutPresets { default: string; presets: Required<LayoutPreset>[] }
export interface LayoutObservation { preset: string; width: number; ok: boolean; failed: string[]; items: number }
export interface LayoutCandidates {
  schema: typeof CANDIDATES;
  default: string;
  presets: Record<string, {passed: number[]; failed: number[]}>;
  by_width: Record<string, string[]>;
  every_width_has_a_candidate: boolean;
  observations: LayoutObservation[];
}
export function validate(spec: unknown): ValidLayoutPresets;
export function css(spec: LayoutPresets): string;
export function controlsHtml(spec: LayoutPresets, candidates?: LayoutCandidates | null, legend?: string): string;
