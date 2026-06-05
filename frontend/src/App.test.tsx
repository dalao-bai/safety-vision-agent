import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import App from "./App";
import type { ChatResponse } from "./types";

const ANALYSIS_RESPONSE: ChatResponse = {
  conversation_id: "conv-1",
  answer: "照片中发现1处隐患。",
  analysis: {
    summary: "存在高空作业隐患",
    hazards: [
      {
        name: "未系安全带",
        location: "脚手架顶部",
        risk_level: "high",
        basis: "工人高处作业无防护",
        remediation: "立即佩戴安全带",
        confidence: 0.9,
      },
    ],
    needs_followup: false,
    followup_question: null,
  },
  tool_calls: [{ tool_name: "analyze_image", status: "success" }],
};

function mockFetchOnce(body: unknown, ok = true, status = 200) {
  return vi.fn().mockResolvedValueOnce({
    ok,
    status,
    json: async () => body,
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("App", () => {
  it("submits a message with image and renders answer + hazards", async () => {
    const fetchMock = mockFetchOnce(ANALYSIS_RESPONSE);
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    const file = new File(["bytes"], "site.jpg", { type: "image/jpeg" });
    const fileInput = screen.getByLabelText("选择施工现场照片") as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });

    fireEvent.change(screen.getByLabelText("消息输入"), {
      target: { value: "请识别这张图的安全隐患" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(screen.getByText("照片中发现1处隐患。")).toBeInTheDocument();
    });
    expect(screen.getByText("未系安全带")).toBeInTheDocument();
    expect(screen.getByText(/脚手架顶部/)).toBeInTheDocument();

    // multipart form sent to /api/chat
    expect(fetchMock).toHaveBeenCalledWith("/api/chat", expect.objectContaining({ method: "POST" }));
    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.get("message")).toBe("请识别这张图的安全隐患");
    expect(body.get("image")).toBeInstanceOf(File);
  });

  it("sends conversation_id and no image on follow-up", async () => {
    // First turn.
    const fetchMock = mockFetchOnce(ANALYSIS_RESPONSE);
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    fireEvent.change(screen.getByLabelText("消息输入"), {
      target: { value: "请识别隐患" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => screen.getByText("照片中发现1处隐患。"));

    // Second turn: follow-up.
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        conversation_id: "conv-1",
        answer: "最严重的是未系安全带。",
        analysis: ANALYSIS_RESPONSE.analysis,
        tool_calls: [{ tool_name: "rank_risks", status: "success" }],
      }),
    });
    fireEvent.change(screen.getByLabelText("消息输入"), {
      target: { value: "哪个最严重" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => screen.getByText("最严重的是未系安全带。"));

    const secondBody = fetchMock.mock.calls[1][1].body as FormData;
    expect(secondBody.get("conversation_id")).toBe("conv-1");
    expect(secondBody.get("image")).toBeNull();
  });

  it("disables submit when message is empty", () => {
    vi.stubGlobal("fetch", vi.fn());
    render(<App />);
    const button = screen.getByRole("button", { name: "发送" }) as HTMLButtonElement;
    expect(button).toBeDisabled();

    fireEvent.change(screen.getByLabelText("消息输入"), {
      target: { value: "hi" },
    });
    expect(button).not.toBeDisabled();
  });

  it("renders an error without clearing the transcript", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: async () => ({ detail: "agent processing failed" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    fireEvent.change(screen.getByLabelText("消息输入"), {
      target: { value: "请识别隐患" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("agent processing failed");
    });
    // User message stays in the transcript.
    expect(screen.getByText("请识别隐患")).toBeInTheDocument();
  });

  it("shows loading state and prevents duplicate submit while in flight", async () => {
    let resolveFetch: (v: unknown) => void;
    const pending = new Promise((res) => {
      resolveFetch = res;
    });
    const fetchMock = vi.fn().mockReturnValueOnce(pending);
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    fireEvent.change(screen.getByLabelText("消息输入"), {
      target: { value: "请识别隐患" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    // Loading indicator visible, button disabled.
    expect(screen.getByText("分析中…")).toBeInTheDocument();
    expect(screen.getByRole("button")).toBeDisabled();

    resolveFetch!({
      ok: true,
      status: 200,
      json: async () => ANALYSIS_RESPONSE,
    });
    await waitFor(() => screen.getByText("照片中发现1处隐患。"));
    // Only one request despite the button being present.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
