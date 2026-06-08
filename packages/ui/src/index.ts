/**
 * @valuegraph/ui — shared design tokens and components, including the source-highlight
 * viewer the Studio and Terminal both use to prove a figure's provenance.
 */

/** Marker export so the package has a typed surface for scaffolding checks. */
export const UI_PACKAGE_VERSION = "0.0.0" as const;

export {
  findQuoteRange,
  highlightStrategy,
  sourceContentUrl,
  textFragmentUrl,
  type HighlightStrategy,
  type SourceRef,
} from "./highlight";
export { SourceHighlight, type SourceHighlightProps } from "./SourceHighlight";
