export interface Metadata {
  prompt?: string;
  request?: string;
  seed?: number;
  model?: string;
  mode?: string;
  width?: number;
  height?: number;
  base_width?: number;
  base_height?: number;
  steps?: number;
  guidance?: number;
  negative_prompt?: string;
  style?: string;
  finish?: string;
  total_seconds?: number;
  texture_from?: unknown;
  layered_document?: string;
  detail_pass?: { option?: string; strength?: number };
  realism_lora?: { strength?: number };
  personal_lora?: { strength?: number };
}
export interface StudioImage {
  name: string;
  url: string;
  thumbnail: string;
  created: number;
  metadata: Metadata;
}
export interface Config {
  models: { id: string; label: string; ready: boolean }[];
  sizes: { id: string; width: number; height: number }[];
  negative_prompt: string;
  assistant: boolean;
  search: boolean;
  repair: boolean;
  references: boolean;
  lora: boolean;
  personal_lora: boolean;
  editing: boolean;
  photocraft?: boolean;
  active_job: string | null;
}
export interface Settings {
  prompt: string;
  model: string;
  size: string;
  seed: string;
  steps: number;
  guidance: number;
  negative_prompt: string;
  detail: string;
  detail_strength: number;
  count: number;
  smart: boolean;
  sketch: string | null;
  sketch_freedom: number;
  vary: boolean;
  check: boolean;
  attempts: number;
  repair: boolean;
  repair_strength: number;
  photo_style: string;
  photo_finish: string;
  combine: boolean;
  references: boolean;
  realism: number;
  personal: number;
}
export interface Job {
  id: string;
  state: 'running' | 'done' | 'cancelled' | 'error';
  progress: number;
  message: string;
  images: StudioImage[];
  understood?: string;
  report?: string;
  sketch?: string;
}
export type Page = 'create' | 'edit' | 'library' | 'krita' | 'photocraft' | 'settings';
export interface LearnedWord {
  phrase: string;
  means: string;
  source: 'taught' | 'correction';
  created: number;
  used: number;
}
export interface PersonalStatus {
  ready: boolean;
  state: 'idle' | 'training' | 'failed';
  message: string;
  progress: number;
  favorites: number;
  minimum: number;
  trained_at: number | null;
  trained_on: number;
  changed: number;
  nightly: boolean;
  minutes: number;
}
export interface Learned {
  words: LearnedWord[];
  strength: Record<string, number>;
  favorites: number;
  profile: { model?: string; size?: string; finish?: string; realism?: number };
  personal: PersonalStatus;
}
