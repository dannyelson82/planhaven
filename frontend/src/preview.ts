/** A short plain-text preview of a note's Markdown copy. Checkbox items are left out when
 * the card shows the checkboxes themselves (including an item's further lines, which follow
 * it without a blank line); Markdown symbols are dropped. */
export function notePreview(markdown: string, withoutChecklist: boolean): string {
  let inItem = false
  return markdown
    .split('\n')
    .filter((line) => {
      if (!withoutChecklist) return true
      if (/^\s*- \[[ x]\]/.test(line)) inItem = true
      else if (!line.trim()) inItem = false
      return !inItem
    })
    .map((line) =>
      line
        .replace(/^\s*(#{1,6}|>|-|\d+\.)\s+/, '')
        .replace(/(\*\*|~~|\*|`)/g, '')
        .trim(),
    )
    .filter(Boolean)
    .join(' · ')
}
