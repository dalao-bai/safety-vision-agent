// API helper for the chat endpoint (U9).
import type { ChatResponse } from "./types";

export interface SendOptions {
  message: string;
  conversationId?: string | null;
  image?: File | null;
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
    this.name = "ApiError";
  }
}

/** Send a message (with optional image) to the chat API. */
export async function sendChat(opts: SendOptions): Promise<ChatResponse> {
  const form = new FormData();
  form.append("message", opts.message);
  if (opts.conversationId) {
    form.append("conversation_id", opts.conversationId);
  }
  if (opts.image) {
    form.append("image", opts.image);
  }

  const resp = await fetch("/api/chat", { method: "POST", body: form });

  if (!resp.ok) {
    let detail = `请求失败 (${resp.status})`;
    try {
      const body = await resp.json();
      if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // non-JSON error body; keep the default detail
    }
    throw new ApiError(detail, resp.status);
  }

  return (await resp.json()) as ChatResponse;
}
