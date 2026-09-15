import { describe, expect, it } from "vitest";
import { parseRoute } from "./router";

describe("parseRoute", () => {
  it("defaults to the dashboard", () => {
    expect(parseRoute("")).toEqual({ name: "dashboard" });
    expect(parseRoute("#/")).toEqual({ name: "dashboard" });
    expect(parseRoute("#/unknown")).toEqual({ name: "dashboard" });
  });

  it("parses projects and project tabs", () => {
    expect(parseRoute("#/projects")).toEqual({ name: "projects" });
    expect(parseRoute("#/projects/abc")).toEqual({ name: "project", id: "abc", tab: "overview" });
    expect(parseRoute("#/projects/abc/tasks")).toEqual({ name: "project", id: "abc", tab: "tasks" });
    expect(parseRoute("#/projects/abc/claims")).toEqual({ name: "project", id: "abc", tab: "claims" });
  });

  it("parses tasks and task detail", () => {
    expect(parseRoute("#/tasks")).toEqual({ name: "tasks" });
    expect(parseRoute("#/tasks/t-1")).toEqual({ name: "task", id: "t-1" });
  });
});
