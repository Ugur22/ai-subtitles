import type { PersonComparisonData } from "./types";

export function splitIntoSections(
  content: string,
): { heading: string; body: string }[] {
  const lines = content.split("\n");
  const sections: { heading: string; body: string }[] = [];
  let currentHeading = "";
  let currentBody: string[] = [];

  const flush = () => {
    if (currentHeading || currentBody.length > 0) {
      sections.push({
        heading: currentHeading,
        body: currentBody.join("\n").trim(),
      });
    }
  };

  // Accept a few heading styles the LLM sometimes emits:
  //   ## Heading        (canonical)
  //   ### Heading       (deeper level)
  //   **Heading**       or **Heading:** on its own line
  const headingPatterns: RegExp[] = [
    /^\s*#{2,6}\s+(.+?)\s*:?\s*$/,
    /^\s*\*\*(.+?)\*\*\s*:?\s*$/,
  ];

  for (const line of lines) {
    let heading: string | null = null;
    for (const re of headingPatterns) {
      const m = line.match(re);
      if (m) {
        heading = m[1].replace(/:$/, "").trim();
        break;
      }
    }
    if (heading) {
      flush();
      currentHeading = heading;
      currentBody = [];
    } else {
      currentBody.push(line);
    }
  }
  flush();
  return sections;
}

export function parsePersonComparisonSection(body: string): {
  metadata: PersonComparisonData | null;
  prose: string;
} {
  const match = body.match(/```json\s*([\s\S]*?)```/i);
  if (!match) {
    return { metadata: null, prose: body.trim() };
  }

  try {
    const metadata = JSON.parse(match[1]) as PersonComparisonData;
    return {
      metadata,
      prose: body.replace(match[0], "").trim(),
    };
  } catch {
    return { metadata: null, prose: body.trim() };
  }
}
