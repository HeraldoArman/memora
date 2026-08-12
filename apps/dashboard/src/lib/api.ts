// ponytail: thin fetch wrappers — one per dashboard endpoint.
// All calls go through Next.js rewrites (/api/dashboard/* → backend), so
// no CORS, no base URL needed in the browser.

const BASE = "/api/dashboard";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`);
  return res.json() as Promise<T>;
}

// --- Types ---

export interface GraphNode {
  label: string;
  name: string;
  person_id?: string;
}

export interface GraphEdge {
  type: string;
  from: string;
  to: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Person {
  person_id: string | null;
  name: string;
  notes: string | null;
  capture_count: number;
}

export interface Memory {
  id: string;
  fact: string;
  category: string | null;
  confidence: number | null;
  person_id: string | null;
  session_id: string | null;
  created_at: string | null;
}

export interface Conversation {
  id: string;
  started_at: string | null;
  ended_at: string | null;
  summary: string | null;
}

export interface Message {
  id: string;
  role: string;
  content: string;
  created_at: string | null;
}

export interface Reminder {
  reminder_id: string;
  title: string;
  note: string | null;
  due_at: string | null;
  completed: boolean;
  created_at: string | null;
}

export interface Event {
  event_id: string;
  title: string;
  description: string | null;
  location: string | null;
  starts_at: string | null;
  ends_at: string | null;
}

export interface ShoppingItem {
  item_id: string;
  name: string;
  quantity: string | null;
  checked: boolean;
  created_at: string | null;
}

export interface HealthStatus {
  status: "ok" | "degraded";
  postgres: string;
  neo4j: string;
  faiss: string;
}

// --- API ---

export const api = {
  graph: () => get<GraphData>("/graph"),
  persons: () => get<Person[]>("/persons"),
  memories: (limit = 50, personId?: string) =>
    get<Memory[]>(`/memories?limit=${limit}${personId ? `&person_id=${personId}` : ""}`),
  conversations: (limit = 20) => get<Conversation[]>(`/conversations?limit=${limit}`),
  messages: (sessionId: string) => get<Message[]>(`/conversations/${sessionId}/messages`),
  remindersToday: () => get<Reminder[]>("/reminders/today"),
  remindersUpcoming: (limit = 20) => get<Reminder[]>(`/reminders/upcoming?limit=${limit}`),
  eventsUpcoming: (limit = 20) => get<Event[]>(`/events/upcoming?limit=${limit}`),
  shopping: () => get<ShoppingItem[]>("/shopping"),
  settings: () => get<Record<string, string>>("/settings"),
  health: () => get<HealthStatus>("/health"),
};
