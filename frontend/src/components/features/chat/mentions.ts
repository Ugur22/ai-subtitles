export const getMentionContext = (value: string, cursorPos: number) => {
  const before = value.slice(0, cursorPos);
  const match = before.match(/@(\S*)$/);
  if (match) {
    return { start: cursorPos - match[0].length, filter: match[1] };
  }
  return null;
};
