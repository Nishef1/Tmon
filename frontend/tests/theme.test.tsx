import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ThemeToggle, THEME_INIT } from "@/components/ThemeToggle";

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("ThemeToggle", () => {
  it("starts light and switches to dark and back, remembering the choice", () => {
    render(<ThemeToggle />);
    const b = screen.getByTestId("theme-toggle");
    expect(b.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(b);
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("tmon-theme")).toBe("dark");
    fireEvent.click(b);
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(localStorage.getItem("tmon-theme")).toBe("light");
  });

  it("the head script only picks dark when the visitor chose it", () => {
    new Function(THEME_INIT)();
    expect(document.documentElement.dataset.theme).toBeUndefined();
    localStorage.setItem("tmon-theme", "dark");
    new Function(THEME_INIT)();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
