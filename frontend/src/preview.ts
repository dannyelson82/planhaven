/** A short plain-text preview of a note's Markdown copy. Checkbox lines are left out when
 * the card shows the checkboxes themselves; Markdown symbols are dropped. */
export function notePreview(markdown: string, withoutChecklist: boolean): string {
  return markdown
    .split('\n')
    .filter((line) => !(withoutChecklist && /^\s*- \[[ x]\]/.test(line)))
    .map((line) =>
      line
        .replace(/^\s*(#{1,6}|>|-|\d+\.)\s+/, '')
        .replace(/(\*\*|~~|\*|`)/g, '')
        .trim(),
    )
    .filter(Boolean)
    .join(' · ')
}
