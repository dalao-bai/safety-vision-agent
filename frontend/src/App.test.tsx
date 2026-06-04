import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import App from "./App";

function mockFetch(handler: (input: RequestInfo | URL) => unknown) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => ({
    ok: true,
    json: async () => handler(input)
  })));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test("upload sets file state and enables chat flow", async () => {
  mockFetch((input) => {
    const url = String(input);
    if (url.endsWith("/api/files/images")) {
      return { file_id: "file_1", filename: "site.jpg", path: "/uploads/site.jpg" };
    }
    return {
      conversation_id: "conv_1",
      answer: "发现 1 处隐患",
      latest_analysis_id: "analysis_1",
      fused_result: { hazards: [], detections: [], uncertain_items: [], uncertain_followups: [], summary: "发现 1 处隐患", recommendations: [] },
      tool_calls: [],
      artifacts: {},
      errors: []
    };
  });

  render(<App />);
  const file = new File(["fake"], "site.jpg", { type: "image/jpeg" });
  fireEvent.change(screen.getByLabelText("上传现场图片"), { target: { files: [file] } });
  await screen.findByText("已上传：site.jpg");

  fireEvent.click(screen.getByRole("button", { name: "发送" }));

  expect(await screen.findAllByText("发现 1 处隐患")).toHaveLength(2);
  expect(screen.getByText("conv_1")).toBeInTheDocument();
});

test("agent error response is shown in message list", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: false,
    json: async () => ({ detail: "Agent 请求失败" })
  })));

  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(screen.getByText("Agent 请求失败")).toBeInTheDocument());
});
