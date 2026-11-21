import { describe, expect, it } from "vitest";
import { getMentionContext } from "./mentions";

describe("getMentionContext", () => {
  it("finds the @token that ends at the cursor", () => {
    expect(getMentionContext("ask @Vi about", 7)).toEqual({ start: 4, filter: "Vi" });
  });

  it("returns null once the token is followed by a space", () => {
    expect(getMentionContext("ask @Vila ", 10)).toBeNull();
  });
});
