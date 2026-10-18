'use strict';
/**
 * Model catalogue for the in-app model picker.
 * Each entry is a preset the user can pick without typing a raw model id.
 * `free: true` means it works with no API key (local / built-in brain).
 */
const MODELS = [
  // --- zero-key ---
  { id: 'auto', provider: 'auto', label: 'Olmavax Auto', note: 'Best available engine', free: true, icon: 'sparkles' },
  { id: 'auto', provider: 'mock', label: 'Olmavax Offline Brain', note: 'Built-in · no key · works offline', free: true, icon: 'brain' },

  // --- Anthropic ---
  { id: 'claude-opus-4-20250514', provider: 'anthropic', label: 'Claude Opus 4', note: 'Deepest reasoning', icon: 'claude' },
  { id: 'claude-sonnet-4-20250514', provider: 'anthropic', label: 'Claude Sonnet 4', note: 'Balanced · recommended', icon: 'claude' },
  { id: 'claude-3-5-haiku-20241022', provider: 'anthropic', label: 'Claude Haiku 3.5', note: 'Fastest · cheapest', icon: 'claude' },

  // --- OpenAI / compatible ---
  { id: 'gpt-4o', provider: 'openai', label: 'GPT-4o', note: 'OpenAI · multimodal', icon: 'openai' },
  { id: 'gpt-4o-mini', provider: 'openai', label: 'GPT-4o mini', note: 'Fast · inexpensive', icon: 'openai' },
  { id: 'gpt-4.1', provider: 'openai', label: 'GPT-4.1', note: 'Long context', icon: 'openai' },
  { id: 'llama-3.3-70b-versatile', provider: 'openai', label: 'Llama 3.3 70B', note: 'Groq / OpenRouter', icon: 'meta' },
  { id: 'deepseek-chat', provider: 'openai', label: 'DeepSeek Chat', note: 'Groq / OpenRouter', icon: 'deepseek' },

  // --- local ---
  { id: 'llama3.2', provider: 'ollama', label: 'Llama 3.2', note: 'Ollama · fully offline', free: true, icon: 'meta' },
  { id: 'llama3.1', provider: 'ollama', label: 'Llama 3.1', note: 'Ollama · fully offline', free: true, icon: 'meta' },
  { id: 'qwen2.5-coder', provider: 'ollama', label: 'Qwen 2.5 Coder', note: 'Ollama · great for code', free: true, icon: 'qwen' },
  { id: 'mistral', provider: 'ollama', label: 'Mistral', note: 'Ollama · fully offline', free: true, icon: 'mistral' },

  // --- advanced sidecar ---
  { id: 'charvis', provider: 'charvis', label: 'OpenCharvis', note: 'Advanced Python agent · memory & tools', icon: 'charvis' },
];

const PROVIDER_NAME = {
  auto: 'Automatic', mock: 'Olmavax Offline Brain', anthropic: 'Anthropic',
  openai: 'OpenAI / compatible', ollama: 'Ollama (local)', charvis: 'OpenCharvis (advanced)',
};

module.exports = { MODELS, PROVIDER_NAME };
