export interface Layer {
  id: number;
  name: string;
  kind: string;
  visible: boolean;
  opacity: number;
  blend?: string;
  selected: boolean;
  hasMask?: boolean;
  clipped?: boolean;
  bounds?: number[] | null;
  text?: { text: string; font: string; sizePt: number };
  adjustment?: Record<string, Record<string, unknown>>;
  smartFilters?: { command: string; params: Record<string, unknown>; visible: boolean }[];
  effects?: { items: { kind: string; enabled: boolean }[] };
  children?: Layer[];
}

export interface Check {
  requirement: number;
  check: string;
  passed: boolean;
}

export interface Verdict {
  requirement: number | null;
  item?: string;
  preserve?: boolean;
  verdict: 'done' | 'partly' | 'not done' | 'unclear';
  note: string;
}

export interface Revision {
  id: string;
  label: string;
  created: number;
  checks?: Check[];
  review?: Verdict[];
  review_error?: string;
  requirements?: string[];
  notes?: string[];
}

export interface DocState {
  width: number;
  height: number;
  mode: string;
  depth: number;
  resolution?: number;
  layers: Layer[];
  activeLayer: number;
  hasSelection: boolean;
}

export interface CraftDocument {
  id: string;
  name: string;
  revision: string;
  preview: string;
  original: string;
  cursor: number;
  history: Revision[];
  can_undo: boolean;
  can_redo: boolean;
  desktop?: object;
  state: DocState;
}

export interface Field {
  name: string;
  type: 'number' | 'choice' | 'bool' | 'color' | 'text' | 'layer' | 'json';
  min?: number | null;
  max?: number | null;
  integer?: boolean;
  default?: number | string | boolean;
  options?: string[];
  optional?: boolean;
  note?: string;
}

export interface Command {
  id: string;
  label: string;
  params: string;
  category: string;
  menu?: string[];
  runnable: boolean;
  reason: string;
  fields: Field[];
}

export interface Edit {
  action: string;
  quote?: string;
  target?: string;
  object?: string;
  direction?: 'increase' | 'decrease' | 'none';
  strength?: 'subtle' | 'moderate' | 'strong';
  value?: number | null;
  text?: string;
  color?: string;
  position?: string;
  size?: string;
  aspect?: string;
  choice?: string;
  explain?: string;
}

export interface Step {
  command: string;
  label: string;
  params: Record<string, unknown>;
  requirements: number[];
  expert?: boolean;
}

export interface Region {
  requirement: number;
  label: string;
  boxes: number[][];
}

export type AreaTool = 'brush' | 'lasso' | 'erase';
export interface AreaMark {
  tool: AreaTool;
  points: [number, number][];
  /** Diameter relative to the document width. */
  size: number;
}
export interface MarkedArea {
  marks: AreaMark[];
}

export interface Plan {
  area?: MarkedArea | null;
  id: string;
  revision: string;
  prompt: string;
  summary: string;
  requirements: string[];
  edits: Edit[];
  preserve: string[];
  questions: string[];
  notes: string[];
  unresolved: string[];
  regions: Region[];
  planner: string;
  steps: Step[];
}

export interface CraftJob {
  id: string;
  state: string;
  message: string;
  progress: number;
  workspace?: CraftDocument;
  plan?: Plan;
}

export interface Capabilities {
  marked_area?: boolean;
  installed: boolean;
  brain: boolean;
  discovered: number;
  runnable: number;
  commands: Command[];
  note: string;
  looks?: string[];
}

/** What every panel can do to the open document. */
export interface Actions {
  document: CraftDocument | null;
  busy: boolean;
  /** Plan-and-apply edits written in the PhotoCraft edit language. */
  edits: (edits: Edit[], label: string) => void;
  /** Run raw engine commands (studio.* steps included). */
  commands: (commands: { command: string; params: object; label?: string }[], label: string) => void;
  error: (message: string) => void;
}

export function flatten(layers: Layer[], depth = 0): (Layer & { depth: number })[] {
  return layers.flatMap((layer) => [{ ...layer, depth }, ...flatten(layer.children || [], depth + 1)]);
}
